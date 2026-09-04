/**
 * Hashcash proof-of-work for signup.
 *
 * The server hands out a random hex challenge and a difficulty. A valid proof
 * is a nonce such that Argon2id(secret = "<challenge>:<nonce>",
 * salt = hex-decoded challenge) begins with `difficulty` zero bits. Argon2id is
 * implemented here so that the client keeps no runtime dependencies; pass a
 * `hashcashSolver` to the client constructor to swap in a WASM implementation.
 */

const BLAKE2B_IV = new Uint32Array([
  0xf3bcc908, 0x6a09e667,
  0x84caa73b, 0xbb67ae85,
  0xfe94f82b, 0x3c6ef372,
  0x5f1d36f1, 0xa54ff53a,
  0xade682d1, 0x510e527f,
  0x2b3e6c1f, 0x9b05688c,
  0xfb41bd6b, 0x1f83d9ab,
  0x137e2179, 0x5be0cd19,
]);

const SIGMA = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
  [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
  [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
  [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
  [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
];

const ARGON2_ID = 2;
const ARGON2_VERSION = 0x13;
const SYNC_POINTS = 4;
const BLOCK_U32 = 256;
const ADDRESSES_IN_BLOCK = 128;

/** High 32 bits of the 64-bit product of two unsigned 32-bit integers. */
function mulHigh32(x, y) {
  const xl = x & 0xffff;
  const xh = x >>> 16;
  const yl = y & 0xffff;
  const yh = y >>> 16;
  const t0 = xl * yl;
  const t1 = xh * yl;
  const t2 = xl * yh;
  const t3 = xh * yh;
  const mid = (t0 >>> 16) + (t1 & 0xffff) + (t2 & 0xffff);
  return (t3 + (t1 >>> 16) + (t2 >>> 16) + (mid >>> 16)) >>> 0;
}

// ---------------------------------------------------------------- BLAKE2b

function blake2bG(v, a, b, c, d, mxLo, mxHi, myLo, myHi) {
  const a0 = a << 1, a1 = a0 + 1;
  const b0 = b << 1, b1 = b0 + 1;
  const c0 = c << 1, c1 = c0 + 1;
  const d0 = d << 1, d1 = d0 + 1;

  let lo = (v[a0] + v[b0]) >>> 0;
  let hi = (v[a1] + v[b1] + (lo < v[a0] ? 1 : 0)) >>> 0;
  let lo2 = (lo + mxLo) >>> 0;
  v[a1] = (hi + mxHi + (lo2 < lo ? 1 : 0)) >>> 0;
  v[a0] = lo2;

  let xl = (v[d0] ^ v[a0]) >>> 0;
  let xh = (v[d1] ^ v[a1]) >>> 0;
  v[d0] = xh;
  v[d1] = xl;

  lo = (v[c0] + v[d0]) >>> 0;
  v[c1] = (v[c1] + v[d1] + (lo < v[c0] ? 1 : 0)) >>> 0;
  v[c0] = lo;

  xl = (v[b0] ^ v[c0]) >>> 0;
  xh = (v[b1] ^ v[c1]) >>> 0;
  v[b0] = ((xl >>> 24) | (xh << 8)) >>> 0;
  v[b1] = ((xh >>> 24) | (xl << 8)) >>> 0;

  lo = (v[a0] + v[b0]) >>> 0;
  hi = (v[a1] + v[b1] + (lo < v[a0] ? 1 : 0)) >>> 0;
  lo2 = (lo + myLo) >>> 0;
  v[a1] = (hi + myHi + (lo2 < lo ? 1 : 0)) >>> 0;
  v[a0] = lo2;

  xl = (v[d0] ^ v[a0]) >>> 0;
  xh = (v[d1] ^ v[a1]) >>> 0;
  v[d0] = ((xl >>> 16) | (xh << 16)) >>> 0;
  v[d1] = ((xh >>> 16) | (xl << 16)) >>> 0;

  lo = (v[c0] + v[d0]) >>> 0;
  v[c1] = (v[c1] + v[d1] + (lo < v[c0] ? 1 : 0)) >>> 0;
  v[c0] = lo;

  xl = (v[b0] ^ v[c0]) >>> 0;
  xh = (v[b1] ^ v[c1]) >>> 0;
  v[b0] = ((xl << 1) | (xh >>> 31)) >>> 0;
  v[b1] = ((xh << 1) | (xl >>> 31)) >>> 0;
}

function blake2bCompress(h, m, v, counterLo, counterHi, last) {
  for (let i = 0; i < 16; i++) v[i] = h[i];
  for (let i = 0; i < 16; i++) v[16 + i] = BLAKE2B_IV[i];

  v[24] = (v[24] ^ counterLo) >>> 0;
  v[25] = (v[25] ^ counterHi) >>> 0;
  if (last) {
    v[28] = ~v[28] >>> 0;
    v[29] = ~v[29] >>> 0;
  }

  for (let r = 0; r < 12; r++) {
    const s = SIGMA[r];
    blake2bG(v, 0, 4, 8, 12, m[s[0] << 1], m[(s[0] << 1) + 1], m[s[1] << 1], m[(s[1] << 1) + 1]);
    blake2bG(v, 1, 5, 9, 13, m[s[2] << 1], m[(s[2] << 1) + 1], m[s[3] << 1], m[(s[3] << 1) + 1]);
    blake2bG(v, 2, 6, 10, 14, m[s[4] << 1], m[(s[4] << 1) + 1], m[s[5] << 1], m[(s[5] << 1) + 1]);
    blake2bG(v, 3, 7, 11, 15, m[s[6] << 1], m[(s[6] << 1) + 1], m[s[7] << 1], m[(s[7] << 1) + 1]);
    blake2bG(v, 0, 5, 10, 15, m[s[8] << 1], m[(s[8] << 1) + 1], m[s[9] << 1], m[(s[9] << 1) + 1]);
    blake2bG(v, 1, 6, 11, 12, m[s[10] << 1], m[(s[10] << 1) + 1], m[s[11] << 1], m[(s[11] << 1) + 1]);
    blake2bG(v, 2, 7, 8, 13, m[s[12] << 1], m[(s[12] << 1) + 1], m[s[13] << 1], m[(s[13] << 1) + 1]);
    blake2bG(v, 3, 4, 9, 14, m[s[14] << 1], m[(s[14] << 1) + 1], m[s[15] << 1], m[(s[15] << 1) + 1]);
  }

  for (let i = 0; i < 16; i++) h[i] = (h[i] ^ v[i] ^ v[16 + i]) >>> 0;
}

/** Keyless BLAKE2b with an output length of 1..64 bytes. */
export function blake2b(input, outlen) {
  const h = new Uint32Array(16);
  h.set(BLAKE2B_IV);
  h[0] = (h[0] ^ 0x01010000 ^ outlen) >>> 0;

  const v = new Uint32Array(32);
  const m = new Uint32Array(32);
  const blocks = Math.max(1, Math.ceil(input.length / 128));

  for (let b = 0; b < blocks; b++) {
    const offset = b * 128;
    const last = b === blocks - 1;
    const available = Math.max(0, input.length - offset);
    const take = last ? available : 128;

    m.fill(0);
    for (let i = 0; i < take; i++) {
      m[i >> 2] = (m[i >> 2] | (input[offset + i] << ((i & 3) << 3))) >>> 0;
    }

    const counted = last ? input.length : offset + 128;
    blake2bCompress(h, m, v, counted >>> 0, Math.floor(counted / 4294967296), last);
  }

  const out = new Uint8Array(outlen);
  for (let i = 0; i < outlen; i++) {
    out[i] = (h[i >> 2] >>> ((i & 3) << 3)) & 0xff;
  }
  return out;
}

/** The Argon2 variable-length hash H'. */
function hPrime(outlen, input) {
  const prefixed = new Uint8Array(4 + input.length);
  writeU32LE(prefixed, 0, outlen);
  prefixed.set(input, 4);

  if (outlen <= 64) return blake2b(prefixed, outlen);

  const out = new Uint8Array(outlen);
  let chunk = blake2b(prefixed, 64);
  out.set(chunk.subarray(0, 32), 0);

  let pos = 32;
  let remaining = outlen - 32;
  while (remaining > 64) {
    chunk = blake2b(chunk, 64);
    out.set(chunk.subarray(0, 32), pos);
    pos += 32;
    remaining -= 32;
  }
  out.set(blake2b(chunk, remaining), pos);
  return out;
}

// ----------------------------------------------------------------- Argon2

/**
 * The Argon2 G function on four 64-bit words of a block, each held as a
 * low/high pair of 32-bit lanes. The additions are the BlaMka variant:
 * x + y + 2 * low32(x) * low32(y).
 */
function blamkaG(v, a, b, c, d) {
  const a0 = a << 1;
  const b0 = b << 1;
  const c0 = c << 1;
  const d0 = d << 1;
  let al = v[a0], ah = v[a0 + 1];
  let bl = v[b0], bh = v[b0 + 1];
  let cl = v[c0], ch = v[c0 + 1];
  let dl = v[d0], dh = v[d0 + 1];
  let t0, t1, t2, t3, mid, plo, phi, sl, sh, nl, xl, xh;

  t0 = (al & 0xffff) * (bl & 0xffff);
  t1 = (al >>> 16) * (bl & 0xffff);
  t2 = (al & 0xffff) * (bl >>> 16);
  t3 = (al >>> 16) * (bl >>> 16);
  mid = (t0 >>> 16) + (t1 & 0xffff) + (t2 & 0xffff);
  plo = ((t0 & 0xffff) | ((mid & 0xffff) << 16)) >>> 0;
  phi = (t3 + (t1 >>> 16) + (t2 >>> 16) + (mid >>> 16)) >>> 0;
  sl = (al + bl) >>> 0;
  sh = (ah + bh + (sl < al ? 1 : 0)) >>> 0;
  nl = (sl + ((plo << 1) >>> 0)) >>> 0;
  ah = (sh + (((phi << 1) | (plo >>> 31)) >>> 0) + (nl < sl ? 1 : 0)) >>> 0;
  al = nl;
  xl = (dl ^ al) >>> 0; xh = (dh ^ ah) >>> 0;
  dl = xh; dh = xl;

  t0 = (cl & 0xffff) * (dl & 0xffff);
  t1 = (cl >>> 16) * (dl & 0xffff);
  t2 = (cl & 0xffff) * (dl >>> 16);
  t3 = (cl >>> 16) * (dl >>> 16);
  mid = (t0 >>> 16) + (t1 & 0xffff) + (t2 & 0xffff);
  plo = ((t0 & 0xffff) | ((mid & 0xffff) << 16)) >>> 0;
  phi = (t3 + (t1 >>> 16) + (t2 >>> 16) + (mid >>> 16)) >>> 0;
  sl = (cl + dl) >>> 0;
  sh = (ch + dh + (sl < cl ? 1 : 0)) >>> 0;
  nl = (sl + ((plo << 1) >>> 0)) >>> 0;
  ch = (sh + (((phi << 1) | (plo >>> 31)) >>> 0) + (nl < sl ? 1 : 0)) >>> 0;
  cl = nl;
  xl = (bl ^ cl) >>> 0; xh = (bh ^ ch) >>> 0;
  bl = ((xl >>> 24) | (xh << 8)) >>> 0;
  bh = ((xh >>> 24) | (xl << 8)) >>> 0;

  t0 = (al & 0xffff) * (bl & 0xffff);
  t1 = (al >>> 16) * (bl & 0xffff);
  t2 = (al & 0xffff) * (bl >>> 16);
  t3 = (al >>> 16) * (bl >>> 16);
  mid = (t0 >>> 16) + (t1 & 0xffff) + (t2 & 0xffff);
  plo = ((t0 & 0xffff) | ((mid & 0xffff) << 16)) >>> 0;
  phi = (t3 + (t1 >>> 16) + (t2 >>> 16) + (mid >>> 16)) >>> 0;
  sl = (al + bl) >>> 0;
  sh = (ah + bh + (sl < al ? 1 : 0)) >>> 0;
  nl = (sl + ((plo << 1) >>> 0)) >>> 0;
  ah = (sh + (((phi << 1) | (plo >>> 31)) >>> 0) + (nl < sl ? 1 : 0)) >>> 0;
  al = nl;
  xl = (dl ^ al) >>> 0; xh = (dh ^ ah) >>> 0;
  dl = ((xl >>> 16) | (xh << 16)) >>> 0;
  dh = ((xh >>> 16) | (xl << 16)) >>> 0;

  t0 = (cl & 0xffff) * (dl & 0xffff);
  t1 = (cl >>> 16) * (dl & 0xffff);
  t2 = (cl & 0xffff) * (dl >>> 16);
  t3 = (cl >>> 16) * (dl >>> 16);
  mid = (t0 >>> 16) + (t1 & 0xffff) + (t2 & 0xffff);
  plo = ((t0 & 0xffff) | ((mid & 0xffff) << 16)) >>> 0;
  phi = (t3 + (t1 >>> 16) + (t2 >>> 16) + (mid >>> 16)) >>> 0;
  sl = (cl + dl) >>> 0;
  sh = (ch + dh + (sl < cl ? 1 : 0)) >>> 0;
  nl = (sl + ((plo << 1) >>> 0)) >>> 0;
  ch = (sh + (((phi << 1) | (plo >>> 31)) >>> 0) + (nl < sl ? 1 : 0)) >>> 0;
  cl = nl;
  xl = (bl ^ cl) >>> 0; xh = (bh ^ ch) >>> 0;
  bl = ((xl << 1) | (xh >>> 31)) >>> 0;
  bh = ((xh << 1) | (xl >>> 31)) >>> 0;

  v[a0] = al; v[a0 + 1] = ah;
  v[b0] = bl; v[b0 + 1] = bh;
  v[c0] = cl; v[c0 + 1] = ch;
  v[d0] = dl; v[d0 + 1] = dh;
}

function blamkaRound(v, w) {
  blamkaG(v, w[0], w[4], w[8], w[12]);
  blamkaG(v, w[1], w[5], w[9], w[13]);
  blamkaG(v, w[2], w[6], w[10], w[14]);
  blamkaG(v, w[3], w[7], w[11], w[15]);
  blamkaG(v, w[0], w[5], w[10], w[15]);
  blamkaG(v, w[1], w[6], w[11], w[12]);
  blamkaG(v, w[2], w[7], w[8], w[13]);
  blamkaG(v, w[3], w[4], w[9], w[14]);
}

const COLUMN_ROUNDS = [];
const ROW_ROUNDS = [];
for (let i = 0; i < 8; i++) {
  const col = new Int32Array(16);
  for (let k = 0; k < 16; k++) col[k] = 16 * i + k;
  COLUMN_ROUNDS.push(col);

  const row = new Int32Array(16);
  for (let k = 0; k < 8; k++) {
    row[2 * k] = 2 * i + 16 * k;
    row[2 * k + 1] = 2 * i + 16 * k + 1;
  }
  ROW_ROUNDS.push(row);
}

function fillBlock(mem, prevOff, refOff, nextOff, withXor, scratch) {
  const r = scratch.r;
  const t = scratch.t;

  for (let i = 0; i < BLOCK_U32; i++) r[i] = (mem[refOff + i] ^ mem[prevOff + i]) >>> 0;
  if (withXor) {
    for (let i = 0; i < BLOCK_U32; i++) t[i] = (r[i] ^ mem[nextOff + i]) >>> 0;
  } else {
    t.set(r);
  }

  for (let i = 0; i < 8; i++) blamkaRound(r, COLUMN_ROUNDS[i]);
  for (let i = 0; i < 8; i++) blamkaRound(r, ROW_ROUNDS[i]);

  for (let i = 0; i < BLOCK_U32; i++) mem[nextOff + i] = (t[i] ^ r[i]) >>> 0;
}

function indexAlpha(pass, slice, index, sameLane, laneLength, segmentLength, j1) {
  let areaSize;
  if (pass === 0) {
    if (slice === 0) {
      areaSize = index - 1;
    } else if (sameLane) {
      areaSize = slice * segmentLength + index - 1;
    } else {
      areaSize = slice * segmentLength + (index === 0 ? -1 : 0);
    }
  } else if (sameLane) {
    areaSize = laneLength - segmentLength + index - 1;
  } else {
    areaSize = laneLength - segmentLength + (index === 0 ? -1 : 0);
  }

  const square = mulHigh32(j1, j1);
  const relative = areaSize - 1 - mulHigh32(areaSize >>> 0, square);

  let start = 0;
  if (pass !== 0) {
    start = slice === SYNC_POINTS - 1 ? 0 : (slice + 1) * segmentLength;
  }
  return (start + relative) % laneLength;
}

function writeU32LE(target, offset, value) {
  target[offset] = value & 0xff;
  target[offset + 1] = (value >>> 8) & 0xff;
  target[offset + 2] = (value >>> 16) & 0xff;
  target[offset + 3] = (value >>> 24) & 0xff;
}

function loadBlock(mem, offset, bytes) {
  for (let i = 0; i < BLOCK_U32; i++) {
    const b = i << 2;
    mem[offset + i] =
      ((bytes[b] | (bytes[b + 1] << 8) | (bytes[b + 2] << 16) | (bytes[b + 3] << 24)) >>> 0);
  }
}

/**
 * Argon2id. `password` and `salt` are Uint8Arrays; the cost parameters match
 * the ones the server publishes with a challenge. `state` may carry a
 * previously allocated memory buffer so repeated attempts reuse it.
 */
export function argon2id(
  { password, salt, timeCost, memoryCost, parallelism, hashLength },
  state = {},
) {
  const lanes = parallelism;
  const clamped = Math.max(memoryCost, 8 * lanes);
  const memoryBlocks = clamped - (clamped % (SYNC_POINTS * lanes));
  const laneLength = memoryBlocks / lanes;
  const segmentLength = laneLength / SYNC_POINTS;

  const needed = memoryBlocks * BLOCK_U32;
  if (!state.mem || state.mem.length !== needed) state.mem = new Uint32Array(needed);
  if (!state.scratch) {
    state.scratch = { r: new Uint32Array(BLOCK_U32), t: new Uint32Array(BLOCK_U32) };
  }
  const mem = state.mem;
  const scratch = state.scratch;

  const preimage = new Uint8Array(40 + password.length + salt.length);
  let p = 0;
  writeU32LE(preimage, p, lanes); p += 4;
  writeU32LE(preimage, p, hashLength); p += 4;
  writeU32LE(preimage, p, memoryCost); p += 4;
  writeU32LE(preimage, p, timeCost); p += 4;
  writeU32LE(preimage, p, ARGON2_VERSION); p += 4;
  writeU32LE(preimage, p, ARGON2_ID); p += 4;
  writeU32LE(preimage, p, password.length); p += 4;
  preimage.set(password, p); p += password.length;
  writeU32LE(preimage, p, salt.length); p += 4;
  preimage.set(salt, p); p += salt.length;
  writeU32LE(preimage, p, 0); p += 4;
  writeU32LE(preimage, p, 0); p += 4;

  const h0 = blake2b(preimage, 64);

  const seed = new Uint8Array(72);
  seed.set(h0, 0);
  for (let lane = 0; lane < lanes; lane++) {
    for (let column = 0; column < 2; column++) {
      writeU32LE(seed, 64, column);
      writeU32LE(seed, 68, lane);
      loadBlock(mem, (lane * laneLength + column) * BLOCK_U32, hPrime(1024, seed));
    }
  }

  const addressBlock = new Uint32Array(BLOCK_U32);
  const inputBlock = new Uint32Array(BLOCK_U32);
  const zeroBlock = new Uint32Array(BLOCK_U32);
  const addressScratch = {
    r: new Uint32Array(BLOCK_U32),
    t: new Uint32Array(BLOCK_U32),
  };
  const addressMem = new Uint32Array(3 * BLOCK_U32);

  const nextAddresses = () => {
    inputBlock[12] = (inputBlock[12] + 1) >>> 0;
    if (inputBlock[12] === 0) inputBlock[13] = (inputBlock[13] + 1) >>> 0;
    addressMem.set(zeroBlock, 0);
    addressMem.set(inputBlock, BLOCK_U32);
    fillBlock(addressMem, 0, BLOCK_U32, 2 * BLOCK_U32, false, addressScratch);
    addressMem.copyWithin(BLOCK_U32, 2 * BLOCK_U32, 3 * BLOCK_U32);
    fillBlock(addressMem, 0, BLOCK_U32, 2 * BLOCK_U32, false, addressScratch);
    addressBlock.set(addressMem.subarray(2 * BLOCK_U32, 3 * BLOCK_U32));
  };

  for (let pass = 0; pass < timeCost; pass++) {
    for (let slice = 0; slice < SYNC_POINTS; slice++) {
      for (let lane = 0; lane < lanes; lane++) {
        const dataIndependent = pass === 0 && slice < SYNC_POINTS / 2;

        if (dataIndependent) {
          inputBlock.fill(0);
          inputBlock[0] = pass;
          inputBlock[2] = lane;
          inputBlock[4] = slice;
          inputBlock[6] = memoryBlocks;
          inputBlock[8] = timeCost;
          inputBlock[10] = ARGON2_ID;
        }

        let startIndex = 0;
        if (pass === 0 && slice === 0) {
          startIndex = 2;
          if (dataIndependent) nextAddresses();
        }

        let current = lane * laneLength + slice * segmentLength + startIndex;
        let previous = current % laneLength === 0 ? current + laneLength - 1 : current - 1;

        for (let index = startIndex; index < segmentLength; index++) {
          if (current % laneLength === 1) previous = current - 1;

          let j1;
          let j2;
          if (dataIndependent) {
            if (index % ADDRESSES_IN_BLOCK === 0) nextAddresses();
            const slot = (index % ADDRESSES_IN_BLOCK) << 1;
            j1 = addressBlock[slot];
            j2 = addressBlock[slot + 1];
          } else {
            j1 = mem[previous * BLOCK_U32];
            j2 = mem[previous * BLOCK_U32 + 1];
          }

          let refLane = j2 % lanes;
          if (pass === 0 && slice === 0) refLane = lane;

          const refIndex = indexAlpha(
            pass, slice, index, refLane === lane, laneLength, segmentLength, j1,
          );

          fillBlock(
            mem,
            previous * BLOCK_U32,
            (refLane * laneLength + refIndex) * BLOCK_U32,
            current * BLOCK_U32,
            pass !== 0,
            scratch,
          );

          current++;
          previous++;
        }
      }
    }
  }

  const final = new Uint32Array(BLOCK_U32);
  final.set(mem.subarray((laneLength - 1) * BLOCK_U32, laneLength * BLOCK_U32));
  for (let lane = 1; lane < lanes; lane++) {
    const off = (lane * laneLength + laneLength - 1) * BLOCK_U32;
    for (let i = 0; i < BLOCK_U32; i++) final[i] = (final[i] ^ mem[off + i]) >>> 0;
  }

  const finalBytes = new Uint8Array(1024);
  for (let i = 0; i < BLOCK_U32; i++) {
    writeU32LE(finalBytes, i << 2, final[i]);
  }
  return hPrime(hashLength, finalBytes);
}

// ----------------------------------------------------------------- solver

/** True when the first `difficulty` bits of `bytes` are zero. */
export function hasLeadingZeroBits(bytes, difficulty) {
  const fullBytes = difficulty >> 3;
  const remainingBits = difficulty & 7;
  if (bytes.length < fullBytes + (remainingBits ? 1 : 0)) return false;
  for (let i = 0; i < fullBytes; i++) {
    if (bytes[i] !== 0) return false;
  }
  if (remainingBits && (bytes[fullBytes] & (0xff << (8 - remainingBits)) & 0xff) !== 0) {
    return false;
  }
  return true;
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length >> 1);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return out;
}

function bytesToHex(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i++) out += bytes[i].toString(16).padStart(2, '0');
  return out;
}

function randomHex(byteLength) {
  const buf = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(buf);
  return bytesToHex(buf);
}

const encoder = new TextEncoder();

/**
 * Search for a nonce that satisfies a challenge from `POST /v1/challenges`.
 * Returns the `{ challenge, nonce }` proof the signup endpoint expects.
 */
export function solveChallenge(challengeResponse) {
  const { challenge, difficulty, params } = challengeResponse;
  const salt = hexToBytes(challenge);
  const state = {};

  for (;;) {
    const nonce = randomHex(16);
    const digest = argon2id(
      {
        password: encoder.encode(`${challenge}:${nonce}`),
        salt,
        timeCost: params.time_cost,
        memoryCost: params.memory_cost,
        parallelism: params.parallelism,
        hashLength: params.hash_len,
      },
      state,
    );
    if (hasLeadingZeroBits(digest, difficulty)) return { challenge, nonce };
  }
}
