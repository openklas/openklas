#!/usr/bin/env python3
"""
Health check script for Azure App Service
Can be used as a standalone health checker or called from monitoring systems
"""

import sys
import os
import asyncio
from typing import Dict, Any

try:
    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine
except ImportError:
    print("ERROR: Required packages not installed")
    sys.exit(1)


async def check_api_health() -> Dict[str, Any]:
    """Check if the API is responding"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://localhost:8000/health",
                timeout=5.0
            )
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
                "details": response.json() if response.status_code == 200 else None
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


async def check_database_health() -> Dict[str, Any]:
    """Check if the database is accessible"""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        return {
            "status": "unknown",
            "error": "DATABASE_URL not set"
        }
    
    try:
        engine = create_async_engine(database_url, echo=False)
        async with engine.begin() as conn:
            result = await conn.execute("SELECT 1")
            row = result.fetchone()
            await engine.dispose()
            
            return {
                "status": "healthy" if row else "unhealthy",
                "connected": True
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "connected": False
        }


async def main():
    """Run all health checks"""
    print("Running KLAS API Health Checks...")
    print("-" * 50)
    
    # Check API
    print("\n1. API Health Check:")
    api_health = await check_api_health()
    print(f"   Status: {api_health['status'].upper()}")
    if 'error' in api_health:
        print(f"   Error: {api_health['error']}")
    
    # Check Database
    print("\n2. Database Health Check:")
    db_health = await check_database_health()
    print(f"   Status: {db_health['status'].upper()}")
    if 'error' in db_health:
        print(f"   Error: {db_health['error']}")
    
    # Overall status
    print("\n" + "-" * 50)
    overall_healthy = (
        api_health['status'] == 'healthy' and 
        db_health['status'] == 'healthy'
    )
    
    if overall_healthy:
        print("✅ All systems healthy")
        sys.exit(0)
    else:
        print("❌ Some systems unhealthy")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
