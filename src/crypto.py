import base64
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import padding


def derive_key(password: str, salt: bytes) -> bytes:
  """Derive a 256-bit (32 bytes) AES key from a password and salt using PBKDF2."""
  kdf = PBKDF2HMAC(
      algorithm=hashes.SHA256(),
      length=32,
      salt=salt,
      iterations=100_000,
  )
  return kdf.derive(password.encode("utf-8"))


def encrypt_aes256(plaintext: str, password: str) -> str:
  """Enkripsi teks menggunakan AES-256-CBC dengan PKCS7 padding.
  
  Format output: Base64(salt [16 bytes] + iv [16 bytes] + ciphertext).
  """
  if not plaintext:
    return ""
  if not password:
    raise ValueError("Password enkripsi tidak boleh kosong.")

  salt = os.urandom(16)
  iv = os.urandom(16)
  key = derive_key(password, salt)

  # PKCS7 padding to 128-bit block size
  padder = padding.PKCS7(128).padder()
  padded_data = padder.update(plaintext.encode("utf-8")) + padder.finalize()

  cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
  encryptor = cipher.encryptor()
  ciphertext = encryptor.update(padded_data) + encryptor.finalize()

  payload = salt + iv + ciphertext
  return base64.b64encode(payload).decode("utf-8")


def decrypt_aes256(encrypted_base64: str, password: str) -> str:
  """Dekripsi teks terenkripsi AES-256-CBC yang dihasilkan oleh encrypt_aes256."""
  if not encrypted_base64:
    return ""
  if not password:
    raise ValueError("Password dekripsi tidak boleh kosong.")

  try:
    payload = base64.b64decode(encrypted_base64.encode("utf-8"))
  except Exception as e:
    raise ValueError("Format data terenkripsi tidak valid.") from e

  if len(payload) < 32:
    raise ValueError("Data terenkripsi terlalu pendek.")

  salt = payload[:16]
  iv = payload[16:32]
  ciphertext = payload[32:]

  key = derive_key(password, salt)

  cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
  decryptor = cipher.decryptor()
  padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

  unpadder = padding.PKCS7(128).unpadder()
  plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

  return plaintext.decode("utf-8")


ENC_CANARY_VALUE = "AUTH_ENCRYPT_VALID_KEY_OK"


def create_encryption_canary(password: str) -> str:
  """Membuat canary encrypted string dengan kata tetap untuk verifikasi password enkripsi."""
  return encrypt_aes256(ENC_CANARY_VALUE, password)


def verify_encryption_canary(encrypted_canary: str, password: str) -> bool:
  """Mengecek apakah kata rahasia canary berhasil didekripsi dengan password yang diberikan.

  Mengembalikan True jika dekripsi berhasil dan teks hasil dekripsi cocok dengan kata tetap.
  """
  if not encrypted_canary or not password:
    return False
  try:
    decrypted = decrypt_aes256(encrypted_canary, password)
    return decrypted == ENC_CANARY_VALUE
  except Exception:
    return False


def encrypt_value(val, password: str) -> str:
  """Mengonversi nilai (str, int, float, bool, dict, list) ke JSON string lalu dienkripsi dengan AES-256."""
  if val is None or val == "":
    return ""
  import json
  plaintext = json.dumps(val, ensure_ascii=False)
  return encrypt_aes256(plaintext, password)


def decrypt_value(encrypted_val: str, password: str, fallback_raw=None, strict: bool = False):
  """Mendekripsi ciphertext AES-256 lalu mengembalikannya ke tipe data aslinya (int, bool, dict, str, dll).

  Jika strict=True, exception akan diteruskan (tidak ditangkap) sehingga caller dapat mendeteksi
  kegagalan dekripsi akibat password salah atau data korup.
  """
  if not encrypted_val:
    return fallback_raw
  import json
  if strict:
    decrypted_str = decrypt_aes256(encrypted_val, password)
    try:
      return json.loads(decrypted_str)
    except Exception:
      return decrypted_str
  else:
    try:
      decrypted_str = decrypt_aes256(encrypted_val, password)
      try:
        return json.loads(decrypted_str)
      except Exception:
        return decrypted_str
    except Exception:
      # Jika gagal dekripsi (misal data lama yang masih plaintext), kembalikan raw
      return encrypted_val if fallback_raw is None else fallback_raw

