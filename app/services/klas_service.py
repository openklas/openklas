"""
KLAS Service - Business logic for interacting with KLAS system
"""
import requests
import json
import base64
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from ..core.config import settings


class KLASService:
    """Service class for KLAS operations"""
    
    def __init__(self):
        self.session = requests.Session()
        self._setup_session()
    
    def _setup_session(self):
        """Setup session headers to mimic browser"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': settings.KLAS_BASE_URL,
            'Referer': settings.KLAS_LOGIN_FORM_URL
        })
    
    def _rsa_encrypt(self, public_key_string: str, plain_text: str) -> Optional[str]:
        """
        RSA encrypt using the public key from the server
        
        Args:
            public_key_string: RSA public key from KLAS
            plain_text: Text to encrypt
            
        Returns:
            Base64 encoded encrypted string or None
        """
        try:
            # Add PEM headers if not present
            if not public_key_string.startswith('-----BEGIN'):
                public_key_string = (
                    f"-----BEGIN PUBLIC KEY-----\n"
                    f"{public_key_string}\n"
                    f"-----END PUBLIC KEY-----"
                )
            
            # Load the public key
            public_key = serialization.load_pem_public_key(
                public_key_string.encode('utf-8'),
                backend=default_backend()
            )
            
            # Encrypt the data
            encrypted = public_key.encrypt(
                plain_text.encode('utf-8'),
                padding.PKCS1v15()
            )
            
            # Return base64 encoded result
            return base64.b64encode(encrypted).decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"RSA encryption failed: {e}")
    
    def _get_public_key(self) -> Optional[str]:
        """
        Get the RSA public key from LoginSecurity endpoint
        
        Returns:
            Public key string or None
        """
        try:
            response = self.session.post(
                settings.KLAS_LOGIN_SECURITY_URL,
                headers={'Content-Type': 'application/json; charset=UTF-8'}
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get('publicKey')
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to get public key: {e}")
    
    def login(self, student_id: str, password: str) -> bool:
        """
        Perform login using RSA encryption
        
        Args:
            student_id: Student ID (학번)
            password: KLAS password
            
        Returns:
            True if login successful, False otherwise
            
        Raises:
            ConnectionError: If connection to KLAS fails
            ValueError: If encryption fails
        """
        # Step 1: Load login form page to establish session
        try:
            self.session.get(settings.KLAS_LOGIN_FORM_URL)
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to load login form: {e}")
        
        # Step 2: Get RSA public key
        public_key = self._get_public_key()
        if not public_key:
            raise ValueError("Failed to get public key")
        
        # Step 3: Create login JSON and encrypt it
        login_data = {
            'loginId': student_id,
            'loginPwd': password,
            'storeIdYn': 'N'
        }
        login_json = json.dumps(login_data, separators=(',', ':'))
        encrypted_token = self._rsa_encrypt(public_key, login_json)
        
        if not encrypted_token:
            raise ValueError("Failed to encrypt credentials")
        
        # Step 4: Check captcha requirement
        try:
            captcha_response = self.session.post(
                settings.KLAS_LOGIN_CAPTCHA_URL,
                json={'loginToken': encrypted_token, 'captcha': ''},
                headers={'Content-Type': 'application/json; charset=UTF-8'}
            )
            
            captcha_count = captcha_response.json()
            if captcha_count > 2:
                raise ValueError("Captcha required after 3+ failed attempts")
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Captcha check failed: {e}")
        
        # Step 5: Submit login
        login_payload = {
            'loginToken': encrypted_token,
            'captcha': '',
            'redirectUrl': '',
            'redirectTabUrl': ''
        }
        
        try:
            login_response = self.session.post(
                settings.KLAS_LOGIN_CONFIRM_URL,
                json=login_payload,
                headers={'Content-Type': 'application/json; charset=UTF-8'}
            )
            
            result = login_response.json()
            
            # Check if login was successful
            if result.get('errorCount') == 0:
                session_cookie = self.session.cookies.get('SESSION')
                return session_cookie is not None
            else:
                return False
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Login request failed: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse login response: {e}")
    
    # Old get profile
    def get_profile_(self) -> Dict[str, Any]:
        """
        Get student profile information from AtnlcScreHakjukInfo.do API
        
        Returns:
            Dictionary containing profile data:
            - name: Student name (이름)
            - student_id: Student ID (학번)
            - major: Major/Department (학과명)
            - category: Category (구분) - 학부/대학원
            - grade: Grade/Year (학년)
            - status: Enrollment status (학적상황)
            - advisor_name: Advisor name (지도교수)
            - advisor_email: Advisor email
            
        Raises:
            ConnectionError: If request fails
            ValueError: If profile data cannot be parsed
        """
        try:
            # Call the direct API endpoint
            response = self.session.post(
                settings.KLAS_STUDENT_INFO_API_URL,
                json={},
                headers={'Content-Type': 'application/json; charset=UTF-8'}
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Map API response to our profile format
            profile = {
                'name': data.get('kname', ''),
                'student_id': data.get('hakbun', ''),
                'major': data.get('hakgwa', ''),
                'category': data.get('gubun', ''),
                'grade': str(data.get('grade', '')) if data.get('grade') else None,
                'status': data.get('hakjukStatu', ''),
                'advisor_name': data.get('jidoName', ''),
                'advisor_email': data.get('email', ''),
            }
            
            # Extract grade from status if grade field is empty but status contains it
            if not profile['grade'] and profile['status']:
                grade_match = re.match(r'(\d+)학년', profile['status'])
                if grade_match:
                    profile['grade'] = grade_match.group(1)
            
            # Clean up status to remove grade if we extracted it
            if profile['grade'] and profile['status']:
                profile['status'] = re.sub(r'\d+학년\s*', '', profile['status']).strip()
            
            return profile
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch profile: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse profile response: {e}")
    
    def get_profile(self) -> Dict[str, Any]:
        """
        Get profile from MyNumberQrStdPage.do
        
        Returns:
            Dictionary containing profile:
            - name: Student name (이름)
            - student_id: Student ID (학번)
            - major: Major/Department (학과명)
            - date_of_birth: Date of birth (생년월일)
            - gender: Gender (성별)
            - nationality: Nationality (국적)
            - profile_image: Profile image as base64 data URI (사진)
            
        Raises:
            ConnectionError: If request fails
            ValueError: If profile cannot be parsed
        """
        try:
            response = self.session.get(
                settings.KLAS_PROFILE_URL,
                headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
            )
            response.raise_for_status()
            
            html_content = response.text
            
            # Extract token from iframe and try DID system first
            token_pattern = r'myidauth\.php\?token=([a-zA-Z0-9._-]+)'
            token_match = re.search(token_pattern, html_content)
            if token_match:
                did_token = token_match.group(1)
                profile = self._fetch_did_profile(did_token)
                if profile and profile.get('name'):
                    return profile
            
            # Fallback: Parse HTML directly from main page
            return self._parse_profile_html(html_content)
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch personal info: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse personal info: {e}")
    
    def _fetch_did_profile(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Fetch profile from DID system using token
        
        Args:
            token: JWT authentication token from KLAS
            
        Returns:
            Profile dictionary or None
        """
        try:
            # DID authentication - this sets session cookies
            auth_url = f"https://did-3.kw.ac.kr/std/app/myidauth.php?token={token}"
            auth_response = self.session.get(auth_url, allow_redirects=True)
            auth_response.raise_for_status()
            
            # Fetch profile page from DID system
            # The info is shown in the "나의 정보" tab (menu=info)
            info_url = "https://did-3.kw.ac.kr/std/app/myidv2_main.php?menu=info"
            info_response = self.session.get(info_url)
            info_response.raise_for_status()
            
            if info_response.status_code == 200:
                profile = self._parse_profile_html(info_response.text)
                # Only return if we got at least name or student_id
                if profile.get('name') or profile.get('student_id'):
                    return profile
                
        except requests.exceptions.RequestException as e:
            # Log error but don't raise - fallback to HTML parsing
            pass
        
        return None
    
    def _parse_profile_html(self, html_content: str) -> Dict[str, Any]:
        """
        Parse profile information from HTML content
        
        Args:
            html_content: HTML page content
            
        Returns:
            Profile dictionary
        """
        profile = {}
        
        # Parse table structure: <th>이름 <small>(Name)</small></th><td>value</td>
        field_patterns = {
            'name': r'<th[^>]*>\s*이름\s*<small[^>]*>\(Name\)</small>\s*</th>\s*<td[^>]*>([^<]+)</td>',
            'student_id': r'<th[^>]*>\s*학번\s*<small[^>]*>\(Student\s*number\)</small>\s*</th>\s*<td[^>]*>([^<]+)</td>',
            'major': r'<th[^>]*>\s*학과명\s*<small[^>]*>\(Major\)</small>\s*</th>\s*<td[^>]*>([^<]+)</td>',
            'date_of_birth': r'<th[^>]*>\s*생년월일\s*<small[^>]*>\(Date\s*of\s*birth\)</small>\s*</th>\s*<td[^>]*>([^<]+)</td>',
            'gender': r'<th[^>]*>\s*성별\s*<small[^>]*>\(Gender\)</small>\s*</th>\s*<td[^>]*>([^<]+)</td>',
            'nationality': r'<th[^>]*>\s*국적\s*<small[^>]*>\(Nationality\)</small>\s*</th>\s*<td[^>]*>([^<]+)</td>',
        }
        
        for field, pattern in field_patterns.items():
            match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1).strip()
                value = re.sub(r'\s+', ' ', value).strip()
                # Remove gender suffix like "(Male)" if present
                if field == 'gender':
                    value = re.sub(r'\s*\([^)]+\)\s*', '', value).strip()
                if value:
                    profile[field] = value
        
        # Extract profile image (base64 data URI)
        # Pattern: <img src="data:image/jpeg;base64,..." or <img src="data:image/png;base64,..."
        image_pattern = r'<img[^>]*src=["\'](data:image/(?:jpeg|jpg|png);base64,[^"\']+)["\']'
        image_match = re.search(image_pattern, html_content, re.IGNORECASE)
        if image_match:
            profile['profile_image'] = image_match.group(1)
        
        return profile
    
    def get_timetable(self, year: Optional[int] = None, semester: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get student timetable data
        
        Args:
            year: Academic year (e.g., 2025). If None, uses current year.
            semester: Semester - "1" for Spring, "2" for Fall. If None, uses current.
            
        Returns:
            List of timetable entries
            
        Raises:
            ConnectionError: If request fails
            ValueError: If response cannot be parsed
        """
        if year is None or semester is None:
            year, semester = self.get_current_year_semester()
        
        try:
            response = self.session.post(
                settings.KLAS_TIMETABLE_URL,
                json={
                    "list": [],
                    "searchYear": str(year),
                    "searchHakgi": semester,
                    "atnlcYearList": [],
                    "timeTableList": []
                },
                headers={'Content-Type': 'application/json; charset=UTF-8'}
            )
            response.raise_for_status()
            return response.json()
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch timetable: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse timetable response: {e}")
    
    def get_university_schedule(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Get university academic schedule (학사일정) from KLAS for a date range.

        Args:
            start_date: Start date YYYY-MM-DD (e.g. "2026-03-01").
            end_date: End date YYYY-MM-DD (e.g. "2026-06-30").

        Returns:
            List of schedule items (raw KLAS response items).

        Raises:
            ConnectionError: If request fails
            ValueError: If response cannot be parsed
        """
        try:
            # KLAS often expects YYYYMMDD for date params
            start_ymd = start_date.replace("-", "")
            end_ymd = end_date.replace("-", "")
            response = self.session.post(
                settings.KLAS_SCHEDULE_URL,
                json={
                    "startDate": start_ymd,
                    "endDate": end_ymd,
                },
                headers={"Content-Type": "application/json; charset=UTF-8"},
            )
            response.raise_for_status()
            data = response.json()
            # KLAS may return a list or an object with a list property
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "list" in data:
                return data["list"]
            if isinstance(data, dict) and "data" in data:
                return data["data"] if isinstance(data["data"], list) else []
            return []
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch university schedule: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse university schedule response: {e}")

    def get_current_year_semester(self) -> tuple[int, str]:
        """
        Get current year and semester based on Korean academic calendar
        
        Returns:
            Tuple of (year, semester) where semester is "1" or "2"
        """
        now = datetime.now()
        year = now.year
        month = now.month
        
        # Spring: March-August, Fall: September-February
        if 3 <= month <= 8:
            semester = "1"
        else:
            semester = "2"
            if month <= 2:  # Jan-Feb belongs to previous year's fall
                year -= 1
        
        return year, semester
    
    def parse_timetable(self, timetable_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Parse raw timetable data into structured format
        
        Args:
            timetable_data: Raw timetable data from KLAS
            
        Returns:
            Dictionary of courses with schedules
        """
        courses = {}
        
        # Time slot mappings
        def get_start_time(index: int) -> tuple[int, int]:
            times = {
                0: (8, 0), 1: (9, 0), 2: (10, 30), 3: (12, 0),
                4: (13, 30), 5: (15, 0), 6: (16, 30), 7: (18, 0),
                8: (18, 50), 9: (19, 40), 10: (20, 30), 11: (21, 30)
            }
            return times.get(index, (0, 0))
        
        def get_end_time(index: int) -> tuple[int, int]:
            times = {
                0: (8, 50), 1: (10, 15), 2: (11, 45), 3: (13, 15),
                4: (14, 45), 5: (16, 15), 6: (17, 45), 7: (18, 45),
                8: (19, 35), 9: (20, 25), 10: (21, 30), 11: (22, 5)
            }
            return times.get(index, (0, 0))
        
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        
        for time_slot in timetable_data:
            wt_time = time_slot.get('wtTime', 0)
            
            # Skip if no schedule
            if time_slot.get('wtHasSchedule') == 'N':
                continue
            
            # Check each day of the week (1-6 = Mon-Sat)
            for day_num in range(1, 7):
                subj_key = f'wtSubj_{day_num}'
                subj_nm_key = f'wtSubjNm_{day_num}'
                loc_key = f'wtLocHname_{day_num}'
                prof_key = f'wtProfNm_{day_num}'
                span_key = f'wtSpan_{day_num}'
                
                if subj_key in time_slot and subj_nm_key in time_slot:
                    course_code = time_slot[subj_key]
                    course_title = time_slot[subj_nm_key]
                    location = time_slot.get(loc_key, '')
                    professor = time_slot.get(prof_key, '')
                    span = time_slot.get(span_key, 1)
                    
                    start_hour, start_min = get_start_time(wt_time)
                    end_hour, end_min = get_end_time(wt_time + span - 1)
                    
                    schedule = {
                        'day': days[day_num - 1],
                        'day_num': day_num - 1,
                        'start_time': f"{start_hour:02d}:{start_min:02d}",
                        'end_time': f"{end_hour:02d}:{end_min:02d}",
                        'location': location,
                        'professor': professor
                    }
                    
                    if course_code not in courses:
                        courses[course_code] = {
                            'course_title': course_title,
                            'course_code': course_code,
                            'schedules': []
                        }
                    
                    courses[course_code]['schedules'].append(schedule)
        
        return courses

