import Foundation

/// Cost parameters the server publishes alongside a challenge.
public struct Argon2Params: Decodable, Sendable {
    public let time_cost: Int
    public let memory_cost: Int
    public let parallelism: Int
    public let hash_len: Int
}

/// A proof-of-work challenge from `POST /v1/challenges`.
public struct HashcashChallenge: Decodable, Sendable {
    public let challenge: String
    public let difficulty: Int
    public let params: Argon2Params
    public let algorithm: String?
    public let expires_in: Int?
}

/// The proof a solved challenge produces, sent with a signup request.
public struct HashcashProof: Codable, Sendable {
    public let challenge: String
    public let nonce: String
}

/// Hashcash proof of work for signup.
///
/// The server issues a random hex challenge and a difficulty. A proof is a
/// nonce for which Argon2id over `"<challenge>:<nonce>"`, salted with the
/// hex-decoded challenge, begins with `difficulty` zero bits. Argon2id is
/// implemented here so the package stays dependency-free.
public enum Hashcash {

    /// Search for a nonce that satisfies `challenge`. This is CPU and memory
    /// intensive; call it off the main actor.
    public static func solve(_ challenge: HashcashChallenge) -> HashcashProof {
        let salt = [UInt8](hex: challenge.challenge)
        let workspace = Argon2Workspace()

        while true {
            let nonce = randomHex(byteCount: 16)
            let secret = Array("\(challenge.challenge):\(nonce)".utf8)
            let digest = Argon2.id(
                password: secret,
                salt: salt,
                timeCost: challenge.params.time_cost,
                memoryCost: challenge.params.memory_cost,
                parallelism: challenge.params.parallelism,
                hashLength: challenge.params.hash_len,
                workspace: workspace
            )
            if hasLeadingZeroBits(digest, difficulty: challenge.difficulty) {
                return HashcashProof(challenge: challenge.challenge, nonce: nonce)
            }
        }
    }

    /// True when the first `difficulty` bits of `bytes` are zero.
    public static func hasLeadingZeroBits(_ bytes: [UInt8], difficulty: Int) -> Bool {
        let fullBytes = difficulty / 8
        let remainingBits = difficulty % 8
        if bytes.count < fullBytes + (remainingBits > 0 ? 1 : 0) { return false }
        for i in 0..<fullBytes where bytes[i] != 0 { return false }
        if remainingBits > 0 {
            let mask = UInt8(truncatingIfNeeded: 0xFF << (8 - remainingBits))
            if bytes[fullBytes] & mask != 0 { return false }
        }
        return true
    }

    private static func randomHex(byteCount: Int) -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        for i in 0..<byteCount { bytes[i] = UInt8.random(in: 0...255) }
        return bytes.hexString
    }
}

// MARK: - BLAKE2b

private let blake2bIV: [UInt64] = [
    0x6a09_e667_f3bc_c908, 0xbb67_ae85_84ca_a73b,
    0x3c6e_f372_fe94_f82b, 0xa54f_f53a_5f1d_36f1,
    0x510e_527f_ade6_82d1, 0x9b05_688c_2b3e_6c1f,
    0x1f83_d9ab_fb41_bd6b, 0x5be0_cd19_137e_2179,
]

private let blake2bSigma: [[Int]] = [
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
]

@inline(__always)
private func rotr64(_ x: UInt64, _ n: UInt64) -> UInt64 {
    (x >> n) | (x << (64 - n))
}

/// Keyless BLAKE2b with an output length of 1...64 bytes.
func blake2b(_ input: [UInt8], outlen: Int) -> [UInt8] {
    var h = blake2bIV
    h[0] ^= 0x0101_0000 ^ UInt64(outlen)

    var v = [UInt64](repeating: 0, count: 16)
    var m = [UInt64](repeating: 0, count: 16)
    let blocks = max(1, (input.count + 127) / 128)

    for block in 0..<blocks {
        let offset = block * 128
        let last = block == blocks - 1
        let take = last ? max(0, input.count - offset) : 128

        for i in 0..<16 { m[i] = 0 }
        for i in 0..<take {
            m[i >> 3] |= UInt64(input[offset + i]) << UInt64((i & 7) * 8)
        }

        let counted = UInt64(last ? input.count : offset + 128)
        blake2bCompress(&h, m, &v, counter: counted, last: last)
    }

    var out = [UInt8](repeating: 0, count: outlen)
    for i in 0..<outlen {
        out[i] = UInt8(truncatingIfNeeded: h[i >> 3] >> UInt64((i & 7) * 8))
    }
    return out
}

private func blake2bCompress(
    _ h: inout [UInt64], _ m: [UInt64], _ v: inout [UInt64], counter: UInt64, last: Bool
) {
    for i in 0..<8 { v[i] = h[i] }
    for i in 0..<8 { v[8 + i] = blake2bIV[i] }

    v[12] ^= counter
    if last { v[14] = ~v[14] }

    @inline(__always)
    func g(_ a: Int, _ b: Int, _ c: Int, _ d: Int, _ x: UInt64, _ y: UInt64) {
        v[a] = v[a] &+ v[b] &+ x
        v[d] = rotr64(v[d] ^ v[a], 32)
        v[c] = v[c] &+ v[d]
        v[b] = rotr64(v[b] ^ v[c], 24)
        v[a] = v[a] &+ v[b] &+ y
        v[d] = rotr64(v[d] ^ v[a], 16)
        v[c] = v[c] &+ v[d]
        v[b] = rotr64(v[b] ^ v[c], 63)
    }

    for round in 0..<12 {
        let s = blake2bSigma[round]
        g(0, 4, 8, 12, m[s[0]], m[s[1]])
        g(1, 5, 9, 13, m[s[2]], m[s[3]])
        g(2, 6, 10, 14, m[s[4]], m[s[5]])
        g(3, 7, 11, 15, m[s[6]], m[s[7]])
        g(0, 5, 10, 15, m[s[8]], m[s[9]])
        g(1, 6, 11, 12, m[s[10]], m[s[11]])
        g(2, 7, 8, 13, m[s[12]], m[s[13]])
        g(3, 4, 9, 14, m[s[14]], m[s[15]])
    }

    for i in 0..<8 { h[i] ^= v[i] ^ v[8 + i] }
}

/// The Argon2 variable-length hash H'.
private func hPrime(outlen: Int, input: [UInt8]) -> [UInt8] {
    var prefixed = [UInt8]()
    prefixed.reserveCapacity(4 + input.count)
    prefixed.append(contentsOf: le32(UInt32(outlen)))
    prefixed.append(contentsOf: input)

    if outlen <= 64 { return blake2b(prefixed, outlen: outlen) }

    var out = [UInt8]()
    out.reserveCapacity(outlen)
    var chunk = blake2b(prefixed, outlen: 64)
    out.append(contentsOf: chunk[0..<32])

    var remaining = outlen - 32
    while remaining > 64 {
        chunk = blake2b(chunk, outlen: 64)
        out.append(contentsOf: chunk[0..<32])
        remaining -= 32
    }
    out.append(contentsOf: blake2b(chunk, outlen: remaining))
    return out
}

// MARK: - Argon2id

private let argon2Type: UInt32 = 2
private let argon2Version: UInt32 = 0x13
private let syncPoints = 4
private let blockWords = 128
private let addressesInBlock = 128

/// Scratch buffers reused across repeated hashing attempts.
final class Argon2Workspace {
    private var blocks = UnsafeMutableBufferPointer<UInt64>(start: nil, count: 0)
    let r = UnsafeMutableBufferPointer<UInt64>.allocate(capacity: blockWords)
    let t = UnsafeMutableBufferPointer<UInt64>.allocate(capacity: blockWords)
    let addresses = UnsafeMutableBufferPointer<UInt64>.allocate(capacity: 3 * blockWords)

    init() {
        r.initialize(repeating: 0)
        t.initialize(repeating: 0)
        addresses.initialize(repeating: 0)
    }

    /// A zeroed block array of the requested size, reallocated only when the
    /// cost parameters change.
    func reserve(blockCount: Int) -> UnsafeMutableBufferPointer<UInt64> {
        let needed = blockCount * blockWords
        if blocks.count != needed {
            blocks.deallocate()
            blocks = UnsafeMutableBufferPointer<UInt64>.allocate(capacity: needed)
        }
        blocks.initialize(repeating: 0)
        return blocks
    }

    deinit {
        blocks.deallocate()
        r.deallocate()
        t.deallocate()
        addresses.deallocate()
    }
}

enum Argon2 {

    /// Argon2id, matching the parameters the server publishes with a challenge.
    static func id(
        password: [UInt8],
        salt: [UInt8],
        timeCost: Int,
        memoryCost: Int,
        parallelism: Int,
        hashLength: Int,
        workspace: Argon2Workspace
    ) -> [UInt8] {
        let lanes = parallelism
        let clamped = max(memoryCost, 8 * lanes)
        let memoryBlocks = clamped - (clamped % (syncPoints * lanes))
        let laneLength = memoryBlocks / lanes
        let segmentLength = laneLength / syncPoints

        let mem = workspace.reserve(blockCount: memoryBlocks)
        let r = workspace.r
        let t = workspace.t
        let addressMem = workspace.addresses

        var preimage = [UInt8]()
        preimage.reserveCapacity(40 + password.count + salt.count)
        preimage.append(contentsOf: le32(UInt32(lanes)))
        preimage.append(contentsOf: le32(UInt32(hashLength)))
        preimage.append(contentsOf: le32(UInt32(memoryCost)))
        preimage.append(contentsOf: le32(UInt32(timeCost)))
        preimage.append(contentsOf: le32(argon2Version))
        preimage.append(contentsOf: le32(argon2Type))
        preimage.append(contentsOf: le32(UInt32(password.count)))
        preimage.append(contentsOf: password)
        preimage.append(contentsOf: le32(UInt32(salt.count)))
        preimage.append(contentsOf: salt)
        preimage.append(contentsOf: le32(0))
        preimage.append(contentsOf: le32(0))

        let h0 = blake2b(preimage, outlen: 64)

        var seed = [UInt8](repeating: 0, count: 72)
        for i in 0..<64 { seed[i] = h0[i] }
        for lane in 0..<lanes {
            for column in 0..<2 {
                writeLE32(&seed, 64, UInt32(column))
                writeLE32(&seed, 68, UInt32(lane))
                loadBlock(mem, (lane * laneLength + column) * blockWords,
                          hPrime(outlen: 1024, input: seed))
            }
        }

        var inputBlock = [UInt64](repeating: 0, count: blockWords)
        var addressBlock = [UInt64](repeating: 0, count: blockWords)

        func nextAddresses() {
            inputBlock[6] &+= 1
            for i in 0..<blockWords { addressMem[i] = 0 }
            for i in 0..<blockWords { addressMem[blockWords + i] = inputBlock[i] }
            fillBlock(addressMem, 0, blockWords, 2 * blockWords, withXor: false, r, t)
            for i in 0..<blockWords { addressMem[blockWords + i] = addressMem[2 * blockWords + i] }
            fillBlock(addressMem, 0, blockWords, 2 * blockWords, withXor: false, r, t)
            for i in 0..<blockWords { addressBlock[i] = addressMem[2 * blockWords + i] }
        }

        for pass in 0..<timeCost {
            for slice in 0..<syncPoints {
                for lane in 0..<lanes {
                    let dataIndependent = pass == 0 && slice < syncPoints / 2

                    if dataIndependent {
                        for i in 0..<blockWords { inputBlock[i] = 0 }
                        inputBlock[0] = UInt64(pass)
                        inputBlock[1] = UInt64(lane)
                        inputBlock[2] = UInt64(slice)
                        inputBlock[3] = UInt64(memoryBlocks)
                        inputBlock[4] = UInt64(timeCost)
                        inputBlock[5] = UInt64(argon2Type)
                    }

                    var startIndex = 0
                    if pass == 0 && slice == 0 {
                        startIndex = 2
                        if dataIndependent { nextAddresses() }
                    }

                    var current = lane * laneLength + slice * segmentLength + startIndex
                    var previous = current % laneLength == 0
                        ? current + laneLength - 1
                        : current - 1

                    for index in startIndex..<segmentLength {
                        if current % laneLength == 1 { previous = current - 1 }

                        let pseudoRandom: UInt64
                        if dataIndependent {
                            if index % addressesInBlock == 0 { nextAddresses() }
                            pseudoRandom = addressBlock[index % addressesInBlock]
                        } else {
                            pseudoRandom = mem[previous * blockWords]
                        }

                        let j1 = UInt32(truncatingIfNeeded: pseudoRandom)
                        let j2 = UInt32(truncatingIfNeeded: pseudoRandom >> 32)

                        var refLane = Int(j2) % lanes
                        if pass == 0 && slice == 0 { refLane = lane }

                        let refIndex = indexAlpha(
                            pass: pass, slice: slice, index: index,
                            sameLane: refLane == lane,
                            laneLength: laneLength, segmentLength: segmentLength, j1: j1
                        )

                        fillBlock(
                            mem,
                            previous * blockWords,
                            (refLane * laneLength + refIndex) * blockWords,
                            current * blockWords,
                            withXor: pass != 0,
                            r, t
                        )

                        current += 1
                        previous += 1
                    }
                }
            }
        }

        var final = [UInt64](repeating: 0, count: blockWords)
        for i in 0..<blockWords { final[i] = mem[(laneLength - 1) * blockWords + i] }
        if lanes > 1 {
            for lane in 1..<lanes {
                let offset = (lane * laneLength + laneLength - 1) * blockWords
                for i in 0..<blockWords { final[i] ^= mem[offset + i] }
            }
        }

        var finalBytes = [UInt8](repeating: 0, count: 1024)
        for i in 0..<blockWords {
            let word = final[i]
            for b in 0..<8 {
                finalBytes[i * 8 + b] = UInt8(truncatingIfNeeded: word >> UInt64(b * 8))
            }
        }
        return hPrime(outlen: hashLength, input: finalBytes)
    }
}

@inline(__always)
private func fBlaMka(_ x: UInt64, _ y: UInt64) -> UInt64 {
    x &+ y &+ (2 &* (x & 0xFFFF_FFFF) &* (y & 0xFFFF_FFFF))
}

@inline(__always)
private func blamkaG(
    _ v: UnsafeMutableBufferPointer<UInt64>, _ a: Int, _ b: Int, _ c: Int, _ d: Int
) {
    v[a] = fBlaMka(v[a], v[b])
    v[d] = rotr64(v[d] ^ v[a], 32)
    v[c] = fBlaMka(v[c], v[d])
    v[b] = rotr64(v[b] ^ v[c], 24)
    v[a] = fBlaMka(v[a], v[b])
    v[d] = rotr64(v[d] ^ v[a], 16)
    v[c] = fBlaMka(v[c], v[d])
    v[b] = rotr64(v[b] ^ v[c], 63)
}

@inline(__always)
private func blamkaRound(
    _ v: UnsafeMutableBufferPointer<UInt64>,
    _ w0: Int, _ w1: Int, _ w2: Int, _ w3: Int,
    _ w4: Int, _ w5: Int, _ w6: Int, _ w7: Int,
    _ w8: Int, _ w9: Int, _ w10: Int, _ w11: Int,
    _ w12: Int, _ w13: Int, _ w14: Int, _ w15: Int
) {
    blamkaG(v, w0, w4, w8, w12)
    blamkaG(v, w1, w5, w9, w13)
    blamkaG(v, w2, w6, w10, w14)
    blamkaG(v, w3, w7, w11, w15)
    blamkaG(v, w0, w5, w10, w15)
    blamkaG(v, w1, w6, w11, w12)
    blamkaG(v, w2, w7, w8, w13)
    blamkaG(v, w3, w4, w9, w14)
}

private func fillBlock(
    _ mem: UnsafeMutableBufferPointer<UInt64>,
    _ prev: Int, _ ref: Int, _ next: Int,
    withXor: Bool,
    _ r: UnsafeMutableBufferPointer<UInt64>,
    _ t: UnsafeMutableBufferPointer<UInt64>
) {
    for i in 0..<blockWords { r[i] = mem[ref + i] ^ mem[prev + i] }
    if withXor {
        for i in 0..<blockWords { t[i] = r[i] ^ mem[next + i] }
    } else {
        for i in 0..<blockWords { t[i] = r[i] }
    }

    for i in 0..<8 {
        let base = 16 * i
        blamkaRound(
            r,
            base, base + 1, base + 2, base + 3, base + 4, base + 5, base + 6, base + 7,
            base + 8, base + 9, base + 10, base + 11, base + 12, base + 13, base + 14, base + 15
        )
    }
    for i in 0..<8 {
        let base = 2 * i
        blamkaRound(
            r,
            base, base + 1, base + 16, base + 17, base + 32, base + 33, base + 48, base + 49,
            base + 64, base + 65, base + 80, base + 81, base + 96, base + 97,
            base + 112, base + 113
        )
    }

    for i in 0..<blockWords { mem[next + i] = t[i] ^ r[i] }
}

private func indexAlpha(
    pass: Int, slice: Int, index: Int, sameLane: Bool,
    laneLength: Int, segmentLength: Int, j1: UInt32
) -> Int {
    let areaSize: Int
    if pass == 0 {
        if slice == 0 {
            areaSize = index - 1
        } else if sameLane {
            areaSize = slice * segmentLength + index - 1
        } else {
            areaSize = slice * segmentLength + (index == 0 ? -1 : 0)
        }
    } else if sameLane {
        areaSize = laneLength - segmentLength + index - 1
    } else {
        areaSize = laneLength - segmentLength + (index == 0 ? -1 : 0)
    }

    let square = (UInt64(j1) &* UInt64(j1)) >> 32
    let relative = Int(UInt64(areaSize) - 1 - ((UInt64(areaSize) &* square) >> 32))

    var start = 0
    if pass != 0 {
        start = slice == syncPoints - 1 ? 0 : (slice + 1) * segmentLength
    }
    return (start + relative) % laneLength
}

private func loadBlock(
    _ mem: UnsafeMutableBufferPointer<UInt64>, _ offset: Int, _ bytes: [UInt8]
) {
    for i in 0..<blockWords {
        var word: UInt64 = 0
        for b in 0..<8 {
            word |= UInt64(bytes[i * 8 + b]) << UInt64(b * 8)
        }
        mem[offset + i] = word
    }
}

// MARK: - Byte helpers

private func le32(_ value: UInt32) -> [UInt8] {
    [
        UInt8(value & 0xFF),
        UInt8((value >> 8) & 0xFF),
        UInt8((value >> 16) & 0xFF),
        UInt8((value >> 24) & 0xFF),
    ]
}

private func writeLE32(_ target: inout [UInt8], _ offset: Int, _ value: UInt32) {
    target[offset] = UInt8(value & 0xFF)
    target[offset + 1] = UInt8((value >> 8) & 0xFF)
    target[offset + 2] = UInt8((value >> 16) & 0xFF)
    target[offset + 3] = UInt8((value >> 24) & 0xFF)
}

extension Array where Element == UInt8 {
    init(hex: String) {
        var bytes = [UInt8]()
        bytes.reserveCapacity(hex.count / 2)
        var index = hex.startIndex
        while index < hex.endIndex {
            let next = hex.index(index, offsetBy: 2, limitedBy: hex.endIndex) ?? hex.endIndex
            if let byte = UInt8(hex[index..<next], radix: 16) { bytes.append(byte) }
            index = next
        }
        self = bytes
    }

    var hexString: String {
        map { String(format: "%02x", $0) }.joined()
    }
}
