import httpx
import json
import time
import asyncio
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urljoin
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, requests_per_minute: int = 60, requests_per_hour: int = 1000):
        self.rpm_limit = requests_per_minute
        self.rph_limit = requests_per_hour
        self.minute_requests = []
        self.hour_requests = []
    
    async def acquire(self):
        now = time.time()
        
        # Clean old requests
        self.minute_requests = [t for t in self.minute_requests if now - t < 60]
        self.hour_requests = [t for t in self.hour_requests if now - t < 3600]
        
        # Check limits
        if len(self.minute_requests) >= self.rpm_limit:
            sleep_time = 60 - (now - self.minute_requests[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        if len(self.hour_requests) >= self.rph_limit:
            sleep_time = 3600 - (now - self.hour_requests[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        # Record this request
        self.minute_requests.append(now)
        self.hour_requests.append(now)


class CacheManager:
    def __init__(self, ttl: int = 300, max_size: int = 1000):
        self.ttl = ttl
        self.max_size = max_size
        self.cache = {}
        self.timestamps = {}
    
    def _is_valid(self, key: str) -> bool:
        if key not in self.timestamps:
            return False
        return time.time() - self.timestamps[key] < self.ttl
    
    def get(self, key: str) -> Optional[Any]:
        if self._is_valid(key):
            return self.cache.get(key)
        elif key in self.cache:
            del self.cache[key]
            del self.timestamps[key]
        return None
    
    def set(self, key: str, value: Any):
        # Clean old entries if cache is full
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.timestamps, key=self.timestamps.get)
            del self.cache[oldest_key]
            del self.timestamps[oldest_key]
        
        self.cache[key] = value
        self.timestamps[key] = time.time()


class ERPNextClient:    
    def __init__(self, url: str, api_key: str, api_secret: str, config: Dict = None):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.api_secret = api_secret
        self.config = config or {}
        
        self.headers = {
            'Authorization': f'token {api_key}:{api_secret}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Initialize components
        rate_config = self.config.get('rate_limiting', {})
        if rate_config.get('enabled', True):
            self.rate_limiter = RateLimiter(
                rate_config.get('requests_per_minute', 60),
                rate_config.get('requests_per_hour', 1000)
            )
        else:
            self.rate_limiter = None
        
        cache_config = self.config.get('cache', {})
        if cache_config.get('enabled', True):
            self.cache = CacheManager(
                cache_config.get('ttl', 300),
                cache_config.get('max_size', 1000)
            )
        else:
            self.cache = None
        
        self.timeout = self.config.get('erpnext', {}).get('timeout', 30)
        
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                           use_cache: bool = True) -> Dict:
        
        # Apply rate limiting
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        
        # Check cache for GET requests
        cache_key = f"{method}:{endpoint}:{json.dumps(data, sort_keys=True) if data else ''}"
        if use_cache and method.upper() == 'GET' and self.cache:
            cached_result = self.cache.get(cache_key)
            if cached_result:
                logger.debug(f"Cache hit for {endpoint}")
                return cached_result
        
        url = urljoin(f"{self.url}/", endpoint.lstrip('/'))
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                start_time = time.time()
                
                if method.upper() == 'GET':
                    response = await client.get(url, headers=self.headers, params=data)
                elif method.upper() == 'POST':
                    response = await client.post(url, headers=self.headers, json=data)
                elif method.upper() == 'PUT':
                    response = await client.put(url, headers=self.headers, json=data)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, headers=self.headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                result = response.json()
                
                # Cache successful GET requests
                if use_cache and method.upper() == 'GET' and self.cache:
                    self.cache.set(cache_key, result)
                
                logger.info(f"{method} {endpoint} - {response.status_code} - {time.time() - start_time:.2f}s")
                return result
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} for {method} {endpoint}: {e.response.text}")
                raise Exception(f"HTTP {e.response.status_code}: {e.response.text}")
            except Exception as e:
                logger.error(f"Request failed for {method} {endpoint}: {str(e)}")
                raise Exception(f"Request failed: {str(e)}")
    
    async def get_doctype_list(self, doctype: str, filters: Optional[Dict] = None, 
                              fields: Optional[List[str]] = None, limit: int = 20) -> Dict:
        """Get list of documents for any doctype"""
        endpoint = f"/api/resource/{doctype}"
        params = {"limit_page_length": limit}
        
        if filters:
            params['filters'] = json.dumps(filters)
        
        if fields:
            params['fields'] = json.dumps(fields)
            
        return await self._make_request('GET', endpoint, params)
    
    async def get_doctype_doc(self, doctype: str, name: str) -> Dict:
        endpoint = f"/api/resource/{doctype}/{name}"
        return await self._make_request('GET', endpoint)
    
    async def create_doctype_doc(self, doctype: str, data: Dict) -> Dict:
        endpoint = f"/api/resource/{doctype}"
        return await self._make_request('POST', endpoint, data, use_cache=False)
    
    async def update_doctype_doc(self, doctype: str, name: str, data: Dict) -> Dict:
        endpoint = f"/api/resource/{doctype}/{name}"
        return await self._make_request('PUT', endpoint, data, use_cache=False)
    
    async def delete_doctype_doc(self, doctype: str, name: str) -> Dict:
        endpoint = f"/api/resource/{doctype}/{name}"
        return await self._make_request('DELETE', endpoint, use_cache=False)
    
    async def get_doctype_meta(self, doctype: str) -> Dict:
        endpoint = f"/api/resource/DocType/{doctype}"
        return await self._make_request('GET', endpoint)
    
    async def search_doctypes(self, doctype: str, search_term: str, limit: int = 10) -> Dict:
        endpoint = f"/api/resource/{doctype}"
        params = {
            "limit_page_length": limit,
            "filters": json.dumps([["name", "like", f"%{search_term}%"]])
        }
        return await self._make_request('GET', endpoint, params)
    
    async def get_linked_documents(self, doctype: str, name: str, link_doctype: str) -> Dict:
        endpoint = f"/api/resource/{link_doctype}"
        params = {
            "filters": json.dumps({doctype.lower().replace(" ", "_"): name}),
            "limit_page_length": 50
        }
        return await self._make_request('GET', endpoint, params)
    
    async def test_connection(self) -> bool:
        try:
            await self._make_request('GET', '/api/method/frappe.auth.get_logged_user', use_cache=False)
            return True
        except Exception:
            return False
    
    async def get_system_info(self) -> Dict:
        try:
            return await self._make_request('GET', '/api/method/frappe.utils.get_system_info', use_cache=False)
        except Exception as e:
            return {"error": str(e)}
    
    async def get_item(self, name: Optional[str] = None, filters: Optional[Dict] = None) -> Dict:
        if name:
            return await self.get_doctype_doc("Item", name)
        else:
            return await self.get_doctype_list("Item", filters)
    
    async def create_item(self, item_data: Dict) -> Dict:
        return await self.create_doctype_doc("Item", item_data)
    
    async def update_item(self, name: str, item_data: Dict) -> Dict:
        return await self.update_doctype_doc("Item", name, item_data)
    
    async def delete_item(self, name: str) -> Dict:
        return await self.delete_doctype_doc("Item", name)