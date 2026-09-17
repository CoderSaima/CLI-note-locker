import os, json
import sys, shutil
from datetime import datetime 
import string, secrets
import time
import base64
import getpass
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# Paths Configuration
BASE_DIR = Path("C:/CLI-Based Secure Note Locker/NoteLocker")
ENCRYPTED_KEY_FILE: Path = BASE_DIR / "secret.key.enc"  
DATA_FILE: Path = BASE_DIR / "enNote.txt"
PASSWORD_FILE: Path = BASE_DIR / "master.hash"
SALT_FILE: Path = BASE_DIR / "system.salt"  
EXPORT_FILE: Path = BASE_DIR / "decrypted_notes.txt"
BACKUP_DIR: Path = BASE_DIR / "Backup"
ATTEMPTS_FILE:Path = BASE_DIR / "attempts.json"

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# Session tracking variables
LAST_ACTIVITY_TIME = time.time()
TIMEOUT_LIMIT = 300  # Sets vault inactivity timeout to 5 minutes (Change to 10 for testing if desired)
MAX_GLOBAL_ATTEMPTS = 10

# ----------------------------
# Check Password Strength
# ----------------------------
def check_pwd_strength(password: str) -> bool:
    if len(password) < 8:
        print("❌ Password must be at least 8 characters\n")
        return False
    if not any(char.isdigit() for char in password):
        print("❌ Password must contain at least one digit\n")
        return False
    if not any(char in "!@#$%^&*(+-`<>" for char in password):
        print("❌ Password must have a special character like @#$%&* etc\n")
        return False
    return True

# ----------------------------
# Make the password into MK
# ----------------------------
def get_master_key(password: str) -> bytes:
    """Transforms your plain text password into a unique mathematical Master Key."""
    if not SALT_FILE.exists():
        salt = os.urandom(16)
        with open(SALT_FILE, "wb") as s:
            s.write(salt)
    else:
        with open(SALT_FILE, "rb") as s:
            salt = s.read()

    # PBKDF2 stretches your password 400,000 times so hackers cannot brute-force it
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=400000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

# ----------------------------
# Initialize the MK if not exists
# ----------------------------
def initialize_key():
    """Sets up encrypted system structures and master password requirements on first launch."""
    if not PASSWORD_FILE.exists() or not ENCRYPTED_KEY_FILE.exists():
        print("---- Setup Master Password ----\n")
        while True:
            password = getpass.getpass("Create a new master password.\n")
            if not check_pwd_strength(password):
                continue
            confirm = getpass.getpass("confirm your password\n")
            
            if password == confirm:
                # 1. Save the confirmation hash to check login matching later
                hashed_pwd = hashlib.sha256(password.encode()).hexdigest()
                with open(PASSWORD_FILE, "w") as w:
                    w.write(hashed_pwd)
                
                # 2. Generate a perfectly random Secret Key for notes encryption
                raw_secret_key = Fernet.generate_key()
                
                # 3. Derive a Master Key wrapper from your typed password string
                master_key = get_master_key(password)
                master_cipher = Fernet(master_key)
                
                # 4. Encrypt the true Secret Key using your derived Master Key wrapper!
                encrypted_secret_key = master_cipher.encrypt(raw_secret_key)
                with open(ENCRYPTED_KEY_FILE, "wb") as k:
                    k.write(encrypted_secret_key)
                
                print("✅ Password and Encrypted Vault Key configured successfully!\n")
                break
            else:
                print("❎ Passwords do not match\n")

#---------------------------------
# Get Failed attempts of user
#----------------------------------                
def get_failed_attempts() -> int:
    """Reads persistent failed attempts across restarts from the disk file."""
    if not ATTEMPTS_FILE.exists():
        return 0
    try:
        with open(ATTEMPTS_FILE, "r") as f:
            data = json.load(f)
            return data.get("failed_count", 0)
    except Exception:
        return 0


# ----------------------------------
# Update failed attpemts 
# ----------------------------------
def update_failed_attempts(count: int):
    """Saves total persistent failed attempts cleanly to the disk file."""
    try:
        with open(ATTEMPTS_FILE, "w") as f:
            json.dump({"failed_count": count}, f)
    except Exception:
        pass

#---------------------------------
# Verify user and load the key
#----------------------------------
def verify_user_and_load_key() -> bytes:
    """Prompts for master password, verifies identity, and unlocks secret key into RAM memory."""
    if not PASSWORD_FILE.exists() or not ENCRYPTED_KEY_FILE.exists():
        print("System files are missing. Please restart to reinitialize.")
        sys.exit()

    with open(PASSWORD_FILE, "r") as r:
        hash_read = r.read().strip()

        print("============================================================")
    print("🔒                SECURE VAULT DOOR LOCK                    🔒")
    print("============================================================")
    
    session_attempts = 3
    while session_attempts > 0:
        global_failed = get_failed_attempts()
        # 🛑 BREACH DETECTION AUTO-WIPE TRIGGER
        if global_failed >= MAX_GLOBAL_ATTEMPTS:
            print(f"\n[🚨 BREACH DETECTION SYSTEM DETECTED {global_failed} TOTAL ATTEMPTS]")
            print("Wiping local note databases automatically to protect critical information...")
            if DATA_FILE.exists():
                os.remove(DATA_FILE)  # 💥 This physically destroys the notes file
            print("Access locked permanently. System shutting down.")
            sys.exit()

        # Displays the persistent count tracker to the user/hacker
        print(f"🔒 [Persistent System Alert: {global_failed}/{MAX_GLOBAL_ATTEMPTS} total failures recorded on disk]")
        enter_pwd = getpass.getpass("Enter your password to unlock the vault:\n")
        enter_hash = hashlib.sha256(enter_pwd.encode()).hexdigest()

        if enter_hash == hash_read:
            try:
                master_key = get_master_key(enter_pwd)
                master_cipher = Fernet(master_key)
                
                with open(ENCRYPTED_KEY_FILE, "rb") as k:
                    encrypted_secret_key = k.read()
                
                decrypted_secret_key = master_cipher.decrypt(encrypted_secret_key)
                
                # Reset counter back to zero on successful login
                update_failed_attempts(0)
                
                global LAST_ACTIVITY_TIME
                LAST_ACTIVITY_TIME = time.time()
                return decrypted_secret_key  
            except Exception:
                print("🚨 Cryptographic recovery failed. System data corrupted.")
                sys.exit()

        session_attempts -= 1
        # Increment the persistent countdown counter on the disk
        update_failed_attempts(global_failed + 1)  
        
        if session_attempts > 0:
            print(f"❌ Incorrect password. {session_attempts} remaining this session\n")
            time.sleep(2)
        else:
            print("🚨 Session locked out. App closing down safely.\n")
            sys.exit()
# ----------------------------
# Verify user and load key
# ----------------------------
def verify_user_and_load_key() -> bytes:
    """Prompts for master password, verifies identity, and unlocks secret key into RAM memory."""
    if not PASSWORD_FILE.exists() or not ENCRYPTED_KEY_FILE.exists():
        print("System files are missing. Please restart to reinitialize.")
        sys.exit()

    with open(PASSWORD_FILE, "r") as r:
        hash_read = r.read().strip()

    attempts = 3
    while attempts > 0:
        enter_pwd = getpass.getpass("Enter your password to unlock the vault:\n")
        enter_hash = hashlib.sha256(enter_pwd.encode()).hexdigest()

        if enter_hash == hash_read:
            try:
                # 1. Derive the temporary Master Key from user password entry
                master_key = get_master_key(enter_pwd)
                master_cipher = Fernet(master_key)
                
                # 2. Read the locked secret key structure from disk
                with open(ENCRYPTED_KEY_FILE, "rb") as k:
                    encrypted_secret_key = k.read()
                
                # 3. Decrypt the Note-locking key back into cleartext memory (RAM)
                decrypted_secret_key = master_cipher.decrypt(encrypted_secret_key)
                
                global LAST_ACTIVITY_TIME
                LAST_ACTIVITY_TIME = time.time()
                return decrypted_secret_key  # Hand back raw bytes to local scope variable
            except Exception:
                print("🚨 Cryptographic recovery failed. System data corrupted.")
                sys.exit()

        attempts -= 1
        if attempts > 0:
            print(f"Incorrect password. {attempts} remaining\n")
            time.sleep(2)
        else:
            print("Too many attempts. Access denied\n")
            sys.exit()

# ----------------------------
# check inactivity 
# ----------------------------
def check_inactivity(current_active_key: bytes) -> bytes:
    """Checks the time delta between operations. Forces re-authentication if threshold crossed."""
    global LAST_ACTIVITY_TIME
    current_time = time.time()
    elapsed_time = current_time - LAST_ACTIVITY_TIME

    if elapsed_time > TIMEOUT_LIMIT:
        print(f"\n[⚠️ SECURITY ALERT] Vault auto-locked due to {int(elapsed_time)} seconds of inactivity.")
        # Re-authenticate and return a freshly loaded memory key string pointer
        return verify_user_and_load_key()
    return current_active_key

# ----------------------------
# Make notes
# ----------------------------
def made_secure_notes(unlocked_key: bytes):
    user_note = input("Enter your secret note...\n")
    if not user_note:
        print("Note file cannot be empty\n")
        return
    tag_input = input("Enter a category tag for this note (e.g., #personal, #work, #banking):\n").strip().lower()
    if not tag_input.startswith("#"):
        tag_input = f"#{tag_input}"

    strutured_note_data = f"[TAG: {tag_input} | {user_note}]"

    cipher = Fernet(unlocked_key)
    encrypted_note = cipher.encrypt(strutured_note_data.encode("utf-8"))

    with open(DATA_FILE, "ab") as b:
        b.write(encrypted_note + b"\n")
        b.flush()

    print(f"[✓] Encrypted and labeled under {tag_input} successfully\n")

# ----------------------------
# View Notes
# ----------------------------
def view_note(unlocked_key: bytes):
    if not DATA_FILE.exists():
        print("\n No encrypted notes found yet.")
        return

    cipher = Fernet(unlocked_key)
    print("---- Decrypted Note ----")
    with open(DATA_FILE, "rb") as f:
        for index, line in enumerate(f, start=1):
            cleaned_line = line.strip()
            if cleaned_line:
                decrypt = cipher.decrypt(cleaned_line)
                print(f"{index}. {decrypt.decode('utf-8')}")
    print(" -------------------------------------------------- ")

# ----------------------------
# Search Notes
# ----------------------------
# -----------------------------------
# Search Notes by Keyword (Option 3)
# -----------------------------------
def search_notes(unlocked_key: bytes):
    if not DATA_FILE.exists():
        print("No encrypted notes found\n")
        return

    # ✨ Changed menu to reflect a real keyword search bar
    keyword = input("Enter keyword or word to search for (e.g., laptop):\n").strip().lower()
    if not keyword:
        print("Search keyword cannot be empty\n")
        return

    cipher = Fernet(unlocked_key)
    print(f"\n---- Search Results for '{keyword}' ----")
    found_any = False

    with open(DATA_FILE, "rb") as b:
        for index, line in enumerate(b, start=1):
            cleaned_line = line.strip()
            if cleaned_line:
                decrypted_note = cipher.decrypt(cleaned_line)
                decoded_str = decrypted_note.decode("utf-8")

                # True keyword matching: checks if the word is inside the note string
                if keyword in decoded_str.lower():
                    # Format output cleanly if it contains a tag structure
                    if "[TAG: " in decoded_str and "] | " in decoded_str:
                        tag_part, note_text = decoded_str.split("] | ", 1)
                        extracted_tag = tag_part.replace("[TAG: ", "").strip()
                        print(f"Line {index}. [{extracted_tag}] {note_text}")
                    else:
                        print(f"Line {index}. {decoded_str}")
                    found_any = True

    if not found_any:
        print("No matches found for that keyword.\n")
    print("-----------------------------------------------------")
# ----------------------------
# Generate secure password
# ----------------------------
def gen_sec_pwd():
    print(" ------ Generating the secure passwrod ------\n")

    try:
        length = int(input("Enter your password length (minimun 8 character)\n"))
        if length < 8:
            print("The password should contain atleast 8 characters\n")
            length = 8
    except ValueError:
        print("Invalid number entered\n")
        length = 12

    alphabets = string.ascii_letters + string.digits + "!@#$%^&*()_+=-~`?></|"
    while True:
        password = "".join(secrets.choice(alphabets)for _ in range(length))
        if (any(char.islower() for char in password) and 
            any(char.isupper() for char in password) and 
            any(char.isdigit() for char in password) and 
            any(char in "!@#$%^&*()_+=-~`?></|" for char in password)):
                break

        print("Your generated secure password\n")
        print("--------------------------------")
        print(f"Password: {password}\n")
        print("--------------------------------")


# ----------------------------
# Change Pwd
# ----------------------------
def change_pwd(unlocked_key: bytes):
    print(" ---- Change Password ----")
    with open(PASSWORD_FILE, "r") as p:
        current_pwd = p.read().strip()

    old_pwd = getpass.getpass("Enter your existing password\n")
    old_hash = hashlib.sha256(old_pwd.encode()).hexdigest()

    if old_hash != current_pwd:
        print("❌ Verification failed. Unauthorized access blocked.\n")
        return
        
    while True:
        new_pwd = getpass.getpass("Enter your new password\n")
        if not check_pwd_strength(new_pwd):
            continue
        confirm_pwd = getpass.getpass("Confirm your new password\n")

        if confirm_pwd == new_pwd:
            # Update verification hash
            new_hash_pwd = hashlib.sha256(new_pwd.encode()).hexdigest()
            with open(PASSWORD_FILE, "w") as w:
                w.write(new_hash_pwd)
            
            new_master_key = get_master_key(new_pwd)
            new_master_cipher = Fernet(new_master_key)
            new_encrypted_key = new_master_cipher.encrypt(unlocked_key)
            
            with open(ENCRYPTED_KEY_FILE, "wb") as k:
                k.write(new_encrypted_key)
                
            print("The password has been updated successfully and the vault re-keyed!\n")
            break
        else:
            print("Passwords do not match. Try again.\n")

# ----------------------------
# Delete file
# ----------------------------
def wipe_vault():
    print("WARNING: YOU ARE ABOUT TO ERASE ALL NOTES PERMANENTLY! 🚨🚨🚨\n")
    print("This action cannot be undone. All encrypted records will be deleted.\n")

    confirm = input("To confirm, Enter 'DELETE'\n").upper().strip()
    if confirm == "DELETE":
        if DATA_FILE.exists():
            try:
                os.remove(DATA_FILE)
                print("\n💥 [SUCCESS] Vault successfully wiped out! All files purged from drive.\n")
                return
            except Exception as e:
                print(f"Error Deleting Data Files {e}\n")
                return
        else:
            print("No encrypted data found to wipe\n")
            return
            
    print("Deletion cancelled\n")

# ------------------------------
# Export Notes
# ------------------------------
def export_notes(unlockkey: bytes):
    if not DATA_FILE.exists():
        print("No files exist\n")
        return
    print("\n⚠️  SECURITY WARNING ⚠️\n")
    print("This will create a completely UNENCRYPTED, plain text file on your drive.\n")
    print("Anyone who gains access to your computer will be able to read your notes.\n")
    confirm = input("Are you absolutely sure you want to export? (yes/no):\n").strip().lower()    

    if confirm != "yes":
        print("Your notes is encrypted safely\n")
        return

    cipher = Fernet(unlockkey)
    try:
        with open(EXPORT_FILE, "w", encoding="utf-8") as out_file:
            with open(DATA_FILE, "rb") as in_file:
                for index, line in enumerate(in_file, start=1):
                    clean_line = line.strip()
                    if clean_line:
                        decrypt = cipher.decrypt(clean_line)
                        plain_text = decrypt.decode("utf-8")
                        out_file.write(f"{index}. {plain_text}\n")
        print(f"\n📂 [SUCCESS] Notes successfully exported in plain text!")
        print(f"📍 File Location: {EXPORT_FILE}")
        print("🔴 CRITICAL: Please delete this file immediately after you are finished using it!\n")

    except Exception as e:
        print(f"Error during exporting {e} \n")

# ---------------------------------
# Create Backup
# ---------------------------------
def create_backup():
    if not DATA_FILE.exists() or not ENCRYPTED_KEY_FILE.exists():
        print("Backup failed: You need to have active notes and keys initialized first.\n")
        return
    
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        backup_data_file = BACKUP_DIR / f"enNote_backup_{timestamp}.txt"
        backup_key_file = BACKUP_DIR / f"secret.key_backup_{timestamp}.enc"
        print("📂 [SUCCESS] Vault data and encryption engine successfully cloned!")
        print(f"📍 Backup Target Directory: {BACKUP_DIR}")
        print(f"📌 Created: enNote_backup_{timestamp}.txt & secret.key_backup_{timestamp}.enc\n")
    except Exception as e:
        print(f"❌ Error compiling automated backup array: {e}")
        print("💡 Hint: If it says 'Permission Denied', try running VS Code / Terminal as Administrator!\n")



# ------------------------------------------------------------------------
# main Block.......
#-------------------------------------------------------------------------
def main():
    global LAST_ACTIVITY_TIME
    initialize_key()
    
    # Unlocks the true key directly into RAM memory exactly once at login
    RAM_SECRET_KEY = verify_user_and_load_key()

    while True:
        print(" ----Menu-----\n")
        print("1- Write a note")
        print("2- Read notes")
        print("3- Search notes by keyword")
        print("4- Change Master Password")
        print("5- Delete all data from File")
        print("6- Export Decrypted Notes to File")
        print("7- Generate a Secure Password")
        print("8- Create a Backup")
        print("9- Exit\n")
        
        choice = input("Enter choice (1-9)\n").strip()

        # Run inactivity timeout check. If it triggers, it updates RAM_SECRET_KEY with new verification session
        RAM_SECRET_KEY = check_inactivity(RAM_SECRET_KEY)
        LAST_ACTIVITY_TIME = time.time()

        if choice == "1":
            made_secure_notes(RAM_SECRET_KEY)
        elif choice == "2":
            view_note(RAM_SECRET_KEY)
        elif choice == "3":
            search_notes(RAM_SECRET_KEY)
        elif choice == "4":
            change_pwd(RAM_SECRET_KEY) 
        elif choice == "5":
            wipe_vault()   
        elif choice == "6":
            export_notes(RAM_SECRET_KEY)
        elif choice == "7":
            gen_sec_pwd()
        elif choice == "8":
            create_backup()
        elif choice == "9":
            print("Have a nice day. Vault locked.")
            # Clear key from scope variable explicitly on exit
            if EXPORT_FILE.exists():
                try:
                    os.remove(EXPORT_FILE)
                    print("🧹 Temporary unencrypted export file scrubbed from disk.")
                except Exception:
                    pass
                    
            print("Have a nice day.\n")
            del RAM_SECRET_KEY
            break
        else:
            print("Wrong Choice. Please Enter valid choice (1-9)\n")

# Tell Python to run the main menu when the script starts
if __name__ == "__main__":
    main()