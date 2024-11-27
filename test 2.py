from cryptography.fernet import Fernet
import os
import base64

new_key = Fernet.generate_key()
print(new_key.decode())

# key = b'YkYKIJrtt4QHN7G9V8DgUCFfyX2GPscY5tdBAHQokf8='
# cipher_suite = Fernet(key)

# secret = "I'm the Admin."
# encrypted_secret = cipher_suite.encrypt(secret.encode('utf-8'))
# print(f"Encrypted Secret: {encrypted_secret}")

# decrypted_secret = cipher_suite.decrypt(encrypted_secret).decode('utf-8')
# print(f"Decrypted Secret: {decrypted_secret}")

# # Ensure that the decrypted secret matches the original
# assert secret == decrypted_secret

# from app import db
# print(db)

from datetime import date, datetime, timedelta

now = datetime.now()
# current_time = now.time()
# print(current_time)
# delete_time = current_time + timedelta(hours=1).time()
# print(delete_time)
today = datetime.today()
print(now.minute)