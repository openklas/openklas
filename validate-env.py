#!/usr/bin/env python3
"""
Environment configuration validator for KLAS API
Checks that all required environment variables are set and valid
"""

import os
import sys
from typing import List, Tuple
from urllib.parse import urlparse


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'


def print_header(text: str):
    print(f"\n{Colors.BLUE}{'=' * 60}")
    print(f"{text}")
    print(f"{'=' * 60}{Colors.END}\n")


def check_required_vars() -> List[Tuple[str, bool, str]]:
    """Check all required environment variables"""
    required_vars = {
        # Database
        'DATABASE_URL': 'PostgreSQL connection string',
        
        # JWT
        'JWT_SECRET': 'JWT signing secret (min 32 chars)',
        
        # KLAS URLs
        'KLAS_BASE_URL': 'KLAS base URL',
        'KLAS_LOGIN_FORM_URL': 'KLAS login form URL',
        'KLAS_LOGIN_SECURITY_URL': 'KLAS login security URL',
        'KLAS_LOGIN_CONFIRM_URL': 'KLAS login confirm URL',
        'KLAS_LOGIN_CAPTCHA_URL': 'KLAS captcha URL',
        'KLAS_TIMETABLE_URL': 'KLAS timetable URL',
        'KLAS_PROFILE_URL': 'KLAS profile URL',
        'KLAS_STUDENT_INFO_URL': 'KLAS student info URL',
        'KLAS_STUDENT_INFO_API_URL': 'KLAS student info API URL',
        'KLAS_SCHEDULE_URL': 'KLAS schedule URL',
        
        # Admin
        'ADMIN_STUDENT_ID': 'Admin student ID',
    }
    
    results = []
    for var, description in required_vars.items():
        value = os.getenv(var)
        is_set = value is not None and value != '' and value != 'https://univerxe.dev/ko'
        results.append((var, is_set, description))
    
    return results


def check_optional_vars() -> List[Tuple[str, bool, str]]:
    """Check optional environment variables"""
    optional_vars = {
        'SENTRY_DSN': 'Sentry error tracking',
        'GOOGLE_SERVICE_ACCOUNT_FILE': 'Google Calendar API',
        'PDF_FONT_PATH': 'PDF font for reports',
        'BACKEND_CORS_ORIGINS': 'CORS allowed origins',
    }
    
    results = []
    for var, description in optional_vars.items():
        value = os.getenv(var)
        is_set = value is not None and value != ''
        results.append((var, is_set, description))
    
    return results


def validate_database_url():
    """Validate DATABASE_URL format"""
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        return False, "Not set"
    
    try:
        parsed = urlparse(db_url)
        if not parsed.scheme.startswith('postgresql'):
            return False, "Must be postgresql:// or postgresql+asyncpg://"
        if not parsed.netloc:
            return False, "Missing host"
        return True, "Valid"
    except Exception as e:
        return False, f"Invalid: {str(e)}"


def validate_jwt_secret():
    """Validate JWT_SECRET length"""
    jwt_secret = os.getenv('JWT_SECRET')
    if not jwt_secret:
        return False, "Not set"
    
    if len(jwt_secret) < 32:
        return False, f"Too short ({len(jwt_secret)} chars, min 32)"
    
    return True, f"Valid ({len(jwt_secret)} chars)"


def validate_urls():
    """Validate KLAS URLs format"""
    url_vars = [
        'KLAS_BASE_URL', 'KLAS_LOGIN_FORM_URL', 'KLAS_LOGIN_SECURITY_URL',
        'KLAS_LOGIN_CONFIRM_URL', 'KLAS_LOGIN_CAPTCHA_URL', 'KLAS_TIMETABLE_URL',
        'KLAS_PROFILE_URL', 'KLAS_STUDENT_INFO_URL', 'KLAS_STUDENT_INFO_API_URL',
        'KLAS_SCHEDULE_URL'
    ]
    
    results = []
    for var in url_vars:
        value = os.getenv(var)
        if not value or value == 'https://univerxe.dev/ko':
            results.append((var, False, "Not set or placeholder"))
        else:
            try:
                parsed = urlparse(value)
                if parsed.scheme in ['http', 'https'] and parsed.netloc:
                    results.append((var, True, "Valid"))
                else:
                    results.append((var, False, "Invalid URL format"))
            except:
                results.append((var, False, "Invalid URL"))
    
    return results


def main():
    print_header("KLAS API Environment Configuration Validator")
    
    # Check required variables
    print(f"{Colors.BLUE}Required Variables:{Colors.END}")
    required_results = check_required_vars()
    all_required_set = all(is_set for _, is_set, _ in required_results)
    
    for var, is_set, description in required_results:
        status = f"{Colors.GREEN}✓{Colors.END}" if is_set else f"{Colors.RED}✗{Colors.END}"
        print(f"  {status} {var:30s} - {description}")
    
    # Detailed validation
    print(f"\n{Colors.BLUE}Detailed Validation:{Colors.END}")
    
    # Database URL
    db_valid, db_msg = validate_database_url()
    status = f"{Colors.GREEN}✓{Colors.END}" if db_valid else f"{Colors.RED}✗{Colors.END}"
    print(f"  {status} DATABASE_URL: {db_msg}")
    
    # JWT Secret
    jwt_valid, jwt_msg = validate_jwt_secret()
    status = f"{Colors.GREEN}✓{Colors.END}" if jwt_valid else f"{Colors.RED}✗{Colors.END}"
    print(f"  {status} JWT_SECRET: {jwt_msg}")
    
    # URLs
    url_results = validate_urls()
    urls_valid = all(is_valid for _, is_valid, _ in url_results)
    status = f"{Colors.GREEN}✓{Colors.END}" if urls_valid else f"{Colors.RED}✗{Colors.END}"
    print(f"  {status} KLAS URLs: {'All valid' if urls_valid else 'Some invalid or missing'}")
    
    # Optional variables
    print(f"\n{Colors.BLUE}Optional Variables:{Colors.END}")
    optional_results = check_optional_vars()
    for var, is_set, description in optional_results:
        status = f"{Colors.GREEN}✓{Colors.END}" if is_set else f"{Colors.YELLOW}○{Colors.END}"
        state = "Set" if is_set else "Not set"
        print(f"  {status} {var:30s} - {description} ({state})")
    
    # Summary
    print_header("Summary")
    
    all_valid = all_required_set and db_valid and jwt_valid and urls_valid
    
    if all_valid:
        print(f"{Colors.GREEN}✅ All required configuration is valid!{Colors.END}")
        print(f"\nYou can now start the application:")
        print(f"  • Development: {Colors.BLUE}make up{Colors.END} or {Colors.BLUE}docker-compose up -d{Colors.END}")
        print(f"  • Production:  {Colors.BLUE}make prod-up{Colors.END} or {Colors.BLUE}docker-compose -f docker-compose.prod.yml up -d{Colors.END}")
        sys.exit(0)
    else:
        print(f"{Colors.RED}❌ Configuration is incomplete or invalid{Colors.END}")
        print(f"\nPlease check the issues above and:")
        print(f"  1. Edit your .env.docker file")
        print(f"  2. Ensure all required variables are set")
        print(f"  3. Run this script again to validate")
        print(f"\nFor help, see:")
        print(f"  • {Colors.BLUE}.env.docker.example{Colors.END} - Template with all variables")
        print(f"  • {Colors.BLUE}DOCKER.md{Colors.END} - Docker setup guide")
        sys.exit(1)


if __name__ == '__main__':
    # Try to load .env.docker if it exists
    env_file = '.env.docker'
    if os.path.exists(env_file):
        print(f"Loading environment from {env_file}...")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
    
    main()
