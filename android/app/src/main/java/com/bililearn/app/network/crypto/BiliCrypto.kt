package com.bililearn.app.network.crypto

import android.util.Base64
import org.bouncycastle.util.io.pem.PemReader
import java.io.StringReader
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher

object BiliCrypto {

    /**
     * Bilibili 账号密码登录 RSA (PKCS1_v1_5) 加密
     */
    fun encryptPassword(password: String, pubKeyPem: String, saltHash: String): String {
        val rawText = (saltHash + password).toByteArray(Charsets.UTF_8)

        val pemReader = PemReader(StringReader(pubKeyPem))
        val pemObject = pemReader.readPemObject()
        pemReader.close()

        val keySpec = X509EncodedKeySpec(pemObject.content)
        val keyFactory = KeyFactory.getInstance("RSA")
        val publicKey = keyFactory.generatePublic(keySpec)

        val cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding")
        cipher.init(Cipher.ENCRYPT_MODE, publicKey)
        val encryptedBytes = cipher.doFinal(rawText)

        return Base64.encodeToString(encryptedBytes, Base64.NO_WRAP)
    }

    /**
     * 计算 MD5 字符串
     */
    fun md5(input: String): String {
        val md = MessageDigest.getInstance("MD5")
        val digest = md.digest(input.toByteArray())
        return digest.joinToString("") { "%02x".format(it) }
    }

    /**
     * 解析 Cookie 字符串为 Map
     */
    fun parseCookieString(cookieStr: String): Map<String, String> {
        val map = mutableMapOf<String, String>()
        if (cookieStr.isBlank()) return map

        val pairs = cookieStr.split(";")
        for (pair in pairs) {
            val trimmed = pair.trim()
            if (trimmed.isEmpty() || !trimmed.contains("=")) continue
            val parts = trimmed.split("=", limit = 2)
            if (parts.size == 2) {
                map[parts[0].trim()] = parts[1].trim()
            }
        }
        return map
    }

    /**
     * 将 Map 组装为 Cookie 请求头
     */
    fun buildCookieHeader(cookies: Map<String, String>): String {
        return cookies.entries.joinToString("; ") { "${it.key}=${it.value}" }
    }
}
