package org.ezauth.client

import java.security.SecureRandom
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bouncycastle.crypto.generators.Argon2BytesGenerator
import org.bouncycastle.crypto.params.Argon2Parameters

/**
 * Hashcash proof of work for signup.
 *
 * The server issues a random hex challenge and a difficulty. A proof is a
 * nonce for which Argon2id over `"<challenge>:<nonce>"`, salted with the
 * hex-decoded challenge, starts with [ChallengeResponse.difficulty] zero bits.
 */
object Hashcash {

    private val random = SecureRandom()

    /** Search for a nonce satisfying [challenge]. Runs on the default dispatcher. */
    suspend fun solve(challenge: ChallengeResponse): HashcashProof =
        withContext(Dispatchers.Default) { solveBlocking(challenge) }

    /** Blocking form of [solve], for callers that manage their own threading. */
    fun solveBlocking(challenge: ChallengeResponse): HashcashProof {
        val salt = challenge.challenge.hexToBytes()
        val params = Argon2Parameters.Builder(Argon2Parameters.ARGON2_id)
            .withVersion(Argon2Parameters.ARGON2_VERSION_13)
            .withIterations(challenge.params.time_cost)
            .withMemoryAsKB(challenge.params.memory_cost)
            .withParallelism(challenge.params.parallelism)
            .withSalt(salt)
            .build()

        val generator = Argon2BytesGenerator()
        generator.init(params)

        val digest = ByteArray(challenge.params.hash_len)
        val nonceBytes = ByteArray(16)

        while (true) {
            random.nextBytes(nonceBytes)
            val nonce = nonceBytes.toHex()
            val secret = "${challenge.challenge}:$nonce".toByteArray(Charsets.UTF_8)
            generator.generateBytes(secret, digest)
            if (hasLeadingZeroBits(digest, challenge.difficulty)) {
                return HashcashProof(challenge = challenge.challenge, nonce = nonce)
            }
        }
    }

    /** True when the first [difficulty] bits of [data] are zero. */
    fun hasLeadingZeroBits(data: ByteArray, difficulty: Int): Boolean {
        val fullBytes = difficulty / 8
        val remainingBits = difficulty % 8
        if (data.size < fullBytes + if (remainingBits > 0) 1 else 0) return false
        for (i in 0 until fullBytes) {
            if (data[i].toInt() != 0) return false
        }
        if (remainingBits > 0) {
            val mask = (0xFF shl (8 - remainingBits)) and 0xFF
            if (data[fullBytes].toInt() and mask != 0) return false
        }
        return true
    }
}

private fun String.hexToBytes(): ByteArray =
    ByteArray(length / 2) { substring(it * 2, it * 2 + 2).toInt(16).toByte() }

private fun ByteArray.toHex(): String =
    joinToString("") { "%02x".format(it) }
