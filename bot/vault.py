"""Seal and unseal files with BLAKE2b and HMAC."""
import hashlib
import hmac
import os
import struct

MAGIC = b"CRV1"
NONCE_LEN = 16
TAG_LEN = 32
BLOCK = 64

def derive(*parts: bytes) -> bytes:
    h = hashlib.blake2b(digest_size=32, person=b"crar-vault-kdf")
    for p in parts:
        h.update(len(p).to_bytes(4, "big"))
        h.update(p)
    return h.digest()

def _keystream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.blake2b(nonce + struct.pack(">Q", counter),
                               key=key, digest_size=BLOCK,
                               person=b"crar-vault-str").digest()
        counter += 1
    return bytes(out[:n])

def _tag(key: bytes, nonce: bytes, body: bytes) -> bytes:
    return hmac.new(key, nonce + body, hashlib.blake2b).digest()[:TAG_LEN]

def seal(data: bytes, key: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    body = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    return MAGIC + nonce + _tag(key, nonce, body) + body

def unseal(blob: bytes, key: bytes) -> bytes:
    head = len(MAGIC) + NONCE_LEN + TAG_LEN
    if len(blob) < head or not blob.startswith(MAGIC):
        raise ValueError("ไม่ใช่ไฟล์ที่ผนึกไว้")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_LEN]
    tag = blob[len(MAGIC) + NONCE_LEN:head]
    body = blob[head:]
    if not hmac.compare_digest(tag, _tag(key, nonce, body)):
        raise ValueError("ไฟล์ถูกแก้ หรือกุญแจไม่ตรง")
    return bytes(a ^ b for a, b in zip(body, _keystream(key, nonce, len(body))))

def pack(files: dict, key: bytes) -> bytes:
    out = bytearray(struct.pack(">H", len(files)))
    for name, data in files.items():
        raw = name.encode("utf-8")
        out += struct.pack(">H", len(raw)) + raw
        out += struct.pack(">I", len(data)) + data
    return seal(bytes(out), key)

def unpack(blob: bytes, key: bytes) -> dict:
    raw = unseal(blob, key)
    pos = 2
    out = {}
    for _ in range(struct.unpack_from(">H", raw, 0)[0]):
        n = struct.unpack_from(">H", raw, pos)[0]
        pos += 2
        name = raw[pos:pos + n].decode("utf-8")
        pos += n
        size = struct.unpack_from(">I", raw, pos)[0]
        pos += 4
        out[name] = raw[pos:pos + size]
        pos += size
    return out
