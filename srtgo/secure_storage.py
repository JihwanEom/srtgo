"""
SRTgo 설정 암호화 저장소 모듈 (keyring 대체용)
"""
import getpass
import hashlib
import json
from pathlib import Path
from Crypto.Cipher import AES

# 설정 파일 경로
CONFIG_DIR = Path.home() / '.srtgo'
CONFIG_FILE = CONFIG_DIR / 'config.encrypted'
KEY_FILE = CONFIG_DIR / '.key'  # 암호화 키 해시를 저장하는 파일

# 기본 설정
DEFAULT_CONFIG = {}
ENCODING = 'utf-8'

class SecureStorage:
    def __init__(self, master_password=None):
        """보안 저장소 초기화"""
        self.ensure_config_dir()
        self.master_password = master_password
        self.encryption_key = None
        self.config = DEFAULT_CONFIG.copy()
        
        # 키 파일이 존재하면 암호화 키 복원 시도
        if self._is_initialized():
            if master_password:
                # 사용자가 직접 비밀번호를 제공한 경우
                self._setup_encryption_key(master_password)
            else:
                # 저장된 키를 사용 시도
                self._try_load_key()
        else:
            # 초기 설정
            self._initial_setup(master_password)
    
    def ensure_config_dir(self):
        """설정 디렉토리가 존재하는지 확인하고 없으면 생성"""
        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    def _is_initialized(self):
        """저장소가 이미 초기화되었는지 확인"""
        return CONFIG_FILE.exists() and KEY_FILE.exists()
    
    def _derive_key(self, password):
        """비밀번호에서 암호화 키 유도"""
        if not password:
            return None
        return hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode(ENCODING), 
            b'srtgo-salt', 
            100000
        )
    
    def _setup_encryption_key(self, password):
        """암호화 키 설정"""
        self.encryption_key = self._derive_key(password)
    
    def _save_key_hash(self):
        """키 파일에 암호화 키의 해시값 저장"""
        if not self.encryption_key:
            return False
        
        key_hash = hashlib.sha256(self.encryption_key).hexdigest()
        with open(KEY_FILE, 'w', encoding=ENCODING) as f:
            f.write(key_hash)
        return True
    
    def _verify_key(self):
        """현재 암호화 키가 올바른지 검증"""
        if not self.encryption_key:
            return False
        
        try:
            with open(KEY_FILE, 'r', encoding=ENCODING) as f:
                stored_hash = f.read().strip()
            
            current_hash = hashlib.sha256(self.encryption_key).hexdigest()
            return stored_hash == current_hash
        except:
            return False
    
    def _try_load_key(self):
        """기존 키 파일에서 암호화 키 해시 확인"""
        if not KEY_FILE.exists():
            return False
        
        # 키 파일이 존재하면 마지막으로 사용한 비밀번호 사용 시도
        if hasattr(self, '_last_password') and self._last_password:
            self._setup_encryption_key(self._last_password)
            if self._verify_key():
                return True
        
        # 비밀번호 입력 요청
        for _ in range(3):  # 최대 3번 시도
            password = getpass.getpass("SRTgo 마스터 비밀번호를 입력하세요: ")
            if not password:
                continue
                
            self._setup_encryption_key(password)
            if self._verify_key():
                # 성공한 비밀번호를 저장
                self._last_password = password
                return True
            
            print("비밀번호가 맞지 않습니다. 다시 시도하세요.")
        
        print("비밀번호 시도 횟수 초과. 기본 설정으로 시작합니다.")
        self.config = DEFAULT_CONFIG.copy()
        return False
    
    def _initial_setup(self, provided_password=None):
        """초기 설정 (최초 실행 시)"""
        # 비밀번호가 제공되지 않은 경우 사용자에게 요청
        password = provided_password or getpass.getpass("SRTgo 마스터 비밀번호 설정 (보안을 위해 입력 문자는 표시되지 않습니다): ")
        
        # 빈 비밀번호를 허용하지 않음
        while not password:
            print("비밀번호는 비워둘 수 없습니다.")
            password = getpass.getpass("SRTgo 마스터 비밀번호 설정: ")
        
        # 비밀번호 확인
        confirm = getpass.getpass("비밀번호 확인: ")
        if password != confirm:
            print("비밀번호가 일치하지 않습니다. 기본 설정으로 시작합니다.")
            self.config = DEFAULT_CONFIG.copy()
            return
        
        # 암호화 키 설정 및 저장
        self._setup_encryption_key(password)
        self._save_key_hash()
        self._last_password = password
        print("비밀번호가 설정되었습니다. 이 비밀번호는 설정을 암호화하는 데 사용됩니다.")
    
    def load(self):
        """암호화된 설정 파일 로드"""
        if not self.encryption_key or not CONFIG_FILE.exists():
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(CONFIG_FILE, 'rb') as f:
                encrypted_data = f.read()
            
            # 암호화된 데이터 구조: nonce(16바이트) + 암호문
            nonce = encrypted_data[:16]
            ciphertext = encrypted_data[16:]
            
            # AES-GCM 복호화
            cipher = AES.new(self.encryption_key, AES.MODE_GCM, nonce=nonce)
            decrypted_data = cipher.decrypt(ciphertext)
            
            # JSON 파싱
            config_json = decrypted_data.decode(ENCODING)
            self.config = json.loads(config_json)
            return self.config
        except Exception as e:
            print(f"설정 로드 중 오류 발생: {e}")
            return DEFAULT_CONFIG.copy()
    
    def save(self):
        """암호화하여 설정 파일 저장"""
        if not self.encryption_key:
            print("암호화 키가 설정되지 않았습니다. 설정을 저장할 수 없습니다.")
            return False
        
        try:
            # 설정을 JSON 문자열로 변환
            config_json = json.dumps(self.config, ensure_ascii=False)
            data = config_json.encode(ENCODING)
            
            # AES-GCM 암호화
            cipher = AES.new(self.encryption_key, AES.MODE_GCM)
            nonce = cipher.nonce
            ciphertext = cipher.encrypt(data)
            
            # 암호화된 데이터 구조: nonce(16바이트) + 암호문
            encrypted_data = nonce + ciphertext
            
            with open(CONFIG_FILE, 'wb') as f:
                f.write(encrypted_data)
            
            return True
        except Exception as e:
            print(f"설정 저장 중 오류 발생: {e}")
            return False
    
    def get(self, service, key, default=None):
        """특정 서비스/키에 대한 값 반환"""
        if not self.config:
            self.load()
        
        service_config = self.config.get(service, {})
        return service_config.get(key, default)
    
    def set(self, service, key, value):
        """특정 서비스/키에 값 설정"""
        if not self.config:
            self.load()
        
        if service not in self.config:
            self.config[service] = {}
        
        self.config[service][key] = value
        return self.save()
    
    def delete(self, service, key):
        """특정 서비스/키 삭제"""
        if not self.config:
            self.load()
        
        if service in self.config and key in self.config[service]:
            del self.config[service][key]
            return self.save()
        return False

# singleton 인스턴스로 사용
_storage = None

def get_storage():
    """저장소 인스턴스 반환"""
    global _storage
    if _storage is None:
        _storage = SecureStorage()
        _storage.load()
    return _storage

# keyring 호환 인터페이스
def get_password(service, key):
    """keyring.get_password 대체 함수"""
    return get_storage().get(service, key)

def set_password(service, key, value):
    """keyring.set_password 대체 함수"""
    return get_storage().set(service, key, value)

def delete_password(service, key):
    """keyring.delete_password 대체 함수"""
    return get_storage().delete(service, key)
