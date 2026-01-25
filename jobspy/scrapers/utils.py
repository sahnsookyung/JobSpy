from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
import logging
from typing import Optional
from urllib.parse import urlparse
import random
import time

logger = logging.getLogger(__name__)

def parse_proxy_string(proxy_str: str) -> dict:
    if not proxy_str:
        return None
    parsed = urlparse(proxy_str)
    proxy_dict = {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    }
    if parsed.username:
        proxy_dict["username"] = parsed.username
    if parsed.password:
        proxy_dict["password"] = parsed.password
    return proxy_dict

def create_playwright_context(
    browser: Browser,
    proxy: Optional[dict] = None,
    user_agent: Optional[str] = None, # Make sure this matches your headers!
    request_timeout: int = 30,
) -> BrowserContext:
    
    # 1. Separate "Context-Level" headers from "Request-Level" headers
    # These headers MUST match the browser engine you are using (e.g. Chrome 130)
    # If your Playwright installs Chromium 131, but you send headers for 130, you will get flagged.
    
    # Define the User-Agent strictly
    final_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

    # 2. Define Extra Headers (Standard Headers)
    # These are safe to send with every request via set_extra_http_headers
    extra_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "priority": "u=0, i",
        "upgrade-insecure-requests": "1",
    }

    # 3. Configure Context Arguments
    context_args = {
        "user_agent": final_ua,
        "viewport": {"width": 1366, "height": 768},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "color_scheme": "dark", # Matches sec-ch-prefers-color-scheme
        
        # EXPERIMENTAL: Try to set client hints via permissions/args if possible, 
        # but Playwright doesn't have a direct "sec_ch_ua" arg in new_context.
        # We handle this by injecting them or relying on the browser to generate them 
        # based on the User-Agent. 
        # WARNING: Manually forcing Sec-CH-UA headers in extra_headers can sometimes 
        # cause "Invalid Header" errors if the browser tries to send them too.
    }

    if proxy:
        context_args["proxy"] = proxy

    context = browser.new_context(**context_args)
    
    # 4. Apply the safe extra headers
    context.set_extra_http_headers(extra_headers)

    # 5. Apply the navigator.webdriver patch
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    context.set_default_timeout(request_timeout * 1000)
    
    return context

def setup_page(context: BrowserContext, block_resources: bool = False) -> Page:
    """
    Creates a new page.
    IMPORTANT: block_resources defaults to False. Blocking fonts/images triggers Cloudflare detection.
    """
    page = context.new_page()
    
    # Only block heavy media if absolutely necessary, but NEVER block fonts/css for Cloudflare
    if block_resources:
        page.route("**/*", route_intercept)
        
    return page

def route_intercept(route):
    """
    Modified to be safer. Only block media/images if you must.
    NEVER block 'font' or 'stylesheet' when fighting Cloudflare.
    """
    request = route.request
    resource_type = request.resource_type
    
    # Block only heavy media, allow fonts/css/scripts
    if resource_type in ["media", "image"]: 
        route.abort()
    else:
        route.continue_()

def human_mouse_move(page: Page):
    """
    Simulates small human-like mouse movements to trigger event listeners.
    """
    try:
        # Move mouse to a random position in the center area
        x = random.randint(300, 800)
        y = random.randint(200, 600)
        page.mouse.move(x, y, steps=10) # steps creates a 'drag' effect rather than teleport
        time.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass

def wait_for_cloudflare_to_clear(page: Page, timeout_ms=60000):
    """
    Waits for the 'Verifying you are human' or Turnstile widget to disappear.
    """
    deadline = time.time() + (timeout_ms / 1000)
    
    while time.time() < deadline:
        # 1. Check if the challenge is still visible
        try:
            # Check for common Turnstile/Cloudflare text
            text_content = page.content().lower()
            if "verifying you are human" not in text_content and "just a moment" not in text_content:
                # 2. Check if we have access to a known element on the target site
                # (Optional: Add a check for an element that SHOULD exist on the target page)
                return True
            
            # 3. Simulate "nervous" user mouse movement while waiting
            human_mouse_move(page)
            
        except Exception:
            pass # Page might be navigating/closed
            
        time.sleep(1) # Wait between checks
        
    raise TimeoutError("Cloudflare interstitial did not clear")
