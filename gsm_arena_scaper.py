import requests
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
import time
import json
from urllib.parse import urljoin, urlparse
import re
import random

# Load environment variables
load_dotenv()

class GSMArenaScraper:
    def __init__(self, delay_between_requests=20):
        self.base_url = "https://www.gsmarena.com/"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.conn = None
        self.cur = None
        self.delay_between_requests = delay_between_requests
        self.last_request_time = 0
        
    def _wait_before_request(self):
        """Ensure minimum delay between requests to avoid IP blocking"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.delay_between_requests:
            wait_time = self.delay_between_requests - time_since_last_request
            # Add some randomization to appear more human-like
            wait_time += random.uniform(1, 5)
            print(f"      ⏸ Waiting {wait_time:.1f} seconds before next request...")
            time.sleep(wait_time)
        
        self.last_request_time = time.time()
    
    def _make_request(self, url, description="page"):
        """Make a request with proper delay and error handling"""
        self._wait_before_request()
        
        try:
            print(f"      → Fetching {description}...")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Check if we got blocked
            if "blocked" in response.text.lower() or response.status_code == 429:
                print(f"      ⚠ WARNING: Possible IP block detected!")
                print(f"      ⏸ Waiting 60 seconds before retrying...")
                time.sleep(60)
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
            
            return response
        except requests.exceptions.RequestException as e:
            print(f"      ✗ Request failed: {e}")
            return None
        
    def connect_db(self):
        """Connect to PostgreSQL database"""
        try:
            self.conn = psycopg2.connect(
                host=os.getenv('DB_HOST'),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                port=os.getenv('DB_PORT', 5432)
            )
            self.cur = self.conn.cursor()
            print("✓ Database connected successfully")
        except Exception as e:
            print(f"✗ Database connection error: {e}")
            raise
    
    def create_tables(self):
        """Create database tables if they don't exist"""
        tables = """
        CREATE TABLE IF NOT EXISTS brands (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            url VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS devices (
            id SERIAL PRIMARY KEY,
            brand_id INTEGER REFERENCES brands(id),
            name VARCHAR(500) NOT NULL,
            url VARCHAR(500) UNIQUE,
            main_image VARCHAR(1000),
            status VARCHAR(255),
            announced VARCHAR(255),
            released VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS device_specifications (
            id SERIAL PRIMARY KEY,
            device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
            category VARCHAR(255),
            spec_key VARCHAR(255),
            spec_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS device_images (
            id SERIAL PRIMARY KEY,
            device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
            image_url VARCHAR(1000),
            image_type VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_devices_brand ON devices(brand_id);
        CREATE INDEX IF NOT EXISTS idx_specs_device ON device_specifications(device_id);
        CREATE INDEX IF NOT EXISTS idx_images_device ON device_images(device_id);
        """
        
        try:
            self.cur.execute(tables)
            self.conn.commit()
            print("✓ Database tables created/verified")
        except Exception as e:
            print(f"✗ Error creating tables: {e}")
            self.conn.rollback()
            raise
    
    def get_brands(self):
        """Scrape all phone brands from GSMArena"""
        try:
            response = self._make_request(self.base_url, "brands page")
            if not response:
                return []
                
            soup = BeautifulSoup(response.content, 'html.parser')
            
            brands = []
            brand_menu = soup.find('div', class_='brandmenu-v2')
            if brand_menu:
                for link in brand_menu.find_all('a', href=True):
                    if link['href'] not in ['search.php3', 'makers.php3', 'rumored.php3']:
                        brand_name = link.text.strip()
                        brand_url = urljoin(self.base_url, link['href'])
                        brands.append((brand_name, brand_url))
            
            print(f"✓ Found {len(brands)} brands")
            return brands
        except Exception as e:
            print(f"✗ Error fetching brands: {e}")
            return []
    
    def extract_brand_name_from_page(self, brand_url):
        """Extract the actual brand name from the brand page"""
        try:
            response = self._make_request(brand_url, "brand page for name extraction")
            if not response:
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract brand name from the page title
            article_hgroup = soup.find('div', class_='article-hgroup')
            if article_hgroup:
                h1_tag = article_hgroup.find('h1', class_='article-info-name')
                if h1_tag:
                    brand_name = h1_tag.text.strip()
                    # Remove " phones" or " devices" suffix if present
                    brand_name = brand_name.replace(' phones', '').replace(' devices', '').strip()
                    return brand_name
            
            return None
        except Exception as e:
            print(f"      ✗ Error extracting brand name: {e}")
            return None
    
    def save_brand(self, brand_name, brand_url):
        """Save brand to database and return brand_id"""
        try:
            self.cur.execute(
                "INSERT INTO brands (name, url) VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET url = EXCLUDED.url RETURNING id",
                (brand_name, brand_url)
            )
            brand_id = self.cur.fetchone()[0]
            self.conn.commit()
            return brand_id
        except Exception as e:
            print(f"✗ Error saving brand {brand_name}: {e}")
            self.conn.rollback()
            return None
    
    def get_next_page_url(self, soup, current_url):
        """Extract next page URL from pagination"""
        try:
            nav_pages = soup.find('div', class_='nav-pages')
            if nav_pages:
                # Find the next button (►)
                next_button = nav_pages.find('a', class_='prevnextbutton', title='Next page')
                if next_button and next_button.get('href'):
                    next_url = urljoin(self.base_url, next_button['href'])
                    return next_url
            return None
        except Exception as e:
            print(f"  ✗ Error finding next page: {e}")
            return None
    
    def get_brand_devices_with_pagination(self, brand_url):
        """Get all device URLs from a brand page with pagination support"""
        all_devices = []
        current_url = brand_url
        page_num = 1
        
        while current_url:
            try:
                print(f"  📄 Fetching device list page {page_num}...")
                response = self._make_request(current_url, f"device list page {page_num}")
                
                if not response:
                    print(f"  ✗ Failed to fetch page {page_num}")
                    break
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract devices from current page
                devices = []
                device_divs = soup.find_all('div', class_='makers')
                for div in device_divs:
                    for link in div.find_all('a', href=True):
                        device_name = link.find('strong')
                        if device_name:
                            device_url = urljoin(self.base_url, link['href'])
                            # Only include phones/tablets, exclude other pages
                            if '.php' in device_url and 'review' not in device_url:
                                devices.append((device_name.text.strip(), device_url))
                
                print(f"    ✓ Found {len(devices)} devices on page {page_num}")
                all_devices.extend(devices)
                
                # Get next page URL
                next_url = self.get_next_page_url(soup, current_url)
                
                if next_url and next_url != current_url:
                    current_url = next_url
                    page_num += 1
                else:
                    break
                    
            except Exception as e:
                print(f"  ✗ Error fetching page {page_num}: {e}")
                break
        
        print(f"  ✓ Total devices found across all pages: {len(all_devices)}")
        return all_devices
    
    def extract_specifications(self, soup):
        """Extract all specifications from device page"""
        specs = []
        
        # Find the specs list container
        specs_list = soup.find('div', id='specs-list')
        if not specs_list:
            print("      ⚠ Warning: specs-list div not found")
            return specs
        
        # Find all specification tables
        tables = specs_list.find_all('table', cellspacing='0')
        
        for table in tables:
            category = None
            
            for row in table.find_all('tr'):
                # Get category from rowspan th
                th = row.find('th', rowspan=True)
                if th:
                    category = th.text.strip()
                
                # Get spec key and value
                ttl = row.find('td', class_='ttl')
                nfo = row.find('td', class_='nfo')
                
                if ttl and nfo and category:
                    spec_key = ttl.text.strip()
                    spec_value = nfo.text.strip()
                    
                    # Clean up spec value
                    spec_value = ' '.join(spec_value.split())
                    
                    if spec_key and spec_value:
                        specs.append({
                            'category': category,
                            'key': spec_key,
                            'value': spec_value
                        })
        
        return specs
    
    def extract_images(self, soup):
        """Extract all images from device page"""
        images = []
        
        # Main image from the center stage
        center_stage = soup.find('div', class_='center-stage')
        if center_stage:
            main_img = center_stage.find('div', class_='specs-photo-main')
            if main_img:
                img = main_img.find('img')
                if img and img.get('src'):
                    images.append({
                        'url': img['src'],
                        'type': 'main'
                    })
        
        # Alternative: Try to find image from review-header
        if not images:
            review_header = soup.find('div', class_='review-header')
            if review_header:
                img = review_header.find('img')
                if img and img.get('src'):
                    images.append({
                        'url': img['src'],
                        'type': 'main'
                    })
        
        # Additional images from picture gallery if exists
        gallery = soup.find('div', id='pictures-list')
        if gallery:
            for img in gallery.find_all('img'):
                if img.get('src'):
                    images.append({
                        'url': img['src'],
                        'type': 'gallery'
                    })
        
        return images
    
    def scrape_device(self, device_name, device_url, brand_id):
        """Scrape individual device specifications"""
        try:
            print(f"    📱 Scraping: {device_name}")
            
            response = self._make_request(device_url, device_name)
            
            if not response:
                print(f"      ✗ Failed to fetch device page")
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check if this is a valid device page
            specs_list = soup.find('div', id='specs-list')
            if not specs_list:
                print(f"      ⚠ Skipping: Not a specifications page (might be review/news)")
                return None
            
            # Extract basic info
            status = soup.find('td', {'data-spec': 'status'})
            status_text = status.text.strip() if status else None
            
            announced = soup.find('td', {'data-spec': 'year'})
            announced_text = announced.text.strip() if announced else None
            
            # Extract released info
            released_elem = soup.find('span', {'data-spec': 'released-hl'})
            released_text = released_elem.text.strip() if released_elem else None
            
            # Extract main image
            main_image = None
            
            # Try multiple methods to find the main image
            # Method 1: specs-photo-main
            center_stage = soup.find('div', class_='center-stage')
            if center_stage:
                main_img_div = center_stage.find('div', class_='specs-photo-main')
                if main_img_div:
                    img = main_img_div.find('img')
                    if img and img.get('src'):
                        main_image = img['src']
            
            # Method 2: review-header (fallback)
            if not main_image:
                review_header = soup.find('div', class_='review-header')
                if review_header:
                    img = review_header.find('img')
                    if img and img.get('src'):
                        main_image = img['src']
            
            # Save device
            self.cur.execute("""
                INSERT INTO devices (brand_id, name, url, main_image, status, announced, released)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    name = EXCLUDED.name,
                    main_image = EXCLUDED.main_image,
                    status = EXCLUDED.status,
                    announced = EXCLUDED.announced,
                    released = EXCLUDED.released
                RETURNING id
            """, (brand_id, device_name, device_url, main_image, status_text, announced_text, released_text))
            
            device_id = self.cur.fetchone()[0]
            self.conn.commit()
            
            # Extract and save specifications
            specs = self.extract_specifications(soup)
            if specs:
                spec_values = [(device_id, s['category'], s['key'], s['value']) for s in specs]
                # Delete old specs first
                self.cur.execute("DELETE FROM device_specifications WHERE device_id = %s", (device_id,))
                execute_values(self.cur, """
                    INSERT INTO device_specifications (device_id, category, spec_key, spec_value)
                    VALUES %s
                """, spec_values)
            
            # Extract and save images
            images = self.extract_images(soup)
            if images:
                image_values = [(device_id, img['url'], img['type']) for img in images]
                # Delete old images first
                self.cur.execute("DELETE FROM device_images WHERE device_id = %s", (device_id,))
                execute_values(self.cur, """
                    INSERT INTO device_images (device_id, image_url, image_type)
                    VALUES %s
                """, image_values)
            
            self.conn.commit()
            
            if specs or images:
                print(f"      ✓ Saved {len(specs)} specs, {len(images)} images")
            else:
                print(f"      ⚠ Warning: No specs or images found")
            
            return device_id
            
        except Exception as e:
            print(f"      ✗ Error scraping {device_name}: {e}")
            self.conn.rollback()
            return None
    
    def scrape_brand(self, brand_url, max_devices=None):
        """Scrape a specific brand with pagination support"""
        print("\n🚀 Starting GSMArena Brand Scraper")
        print(f"⏱  Delay between requests: {self.delay_between_requests} seconds\n")
        
        # Connect to database
        self.connect_db()
        self.create_tables()
        
        # Extract brand name from the page
        print(f"Fetching brand page to extract name...")
        brand_name = self.extract_brand_name_from_page(brand_url)
        
        # Fallback: extract from URL if page extraction fails
        if not brand_name:
            print("⚠ Could not extract brand name from page, using URL fallback")
            brand_name = brand_url.split('/')[-1].replace('-phones-', ' ').replace('.php', '').title()
            brand_name = brand_name.split('-')[0]
        
        print(f"Processing brand: {brand_name}")
        
        # Save brand
        brand_id = self.save_brand(brand_name, brand_url)
        if not brand_id:
            print("✗ Failed to save brand")
            return
        
        # Get all devices with pagination
        devices = self.get_brand_devices_with_pagination(brand_url)
        
        if max_devices:
            devices = devices[:max_devices]
            print(f"\n  Limiting to {max_devices} devices for testing")
        
        # Scrape each device
        total_scraped = 0
        failed = 0
        
        for i, (device_name, device_url) in enumerate(devices, 1):
            print(f"\n  [{i}/{len(devices)}]")
            device_id = self.scrape_device(device_name, device_url, brand_id)
            
            if device_id:
                total_scraped += 1
            else:
                failed += 1
        
        print(f"\n✅ Scraping completed!")
        print(f"   Total devices scraped: {total_scraped}/{len(devices)}")
        print(f"   Failed: {failed}")
    
    def scrape_all(self, max_brands=None, max_devices_per_brand=None):
        """Scrape all brands with pagination support"""
        print("\n🚀 Starting GSMArena Full Scraper")
        print(f"⏱  Delay between requests: {self.delay_between_requests} seconds\n")
        
        # Connect to database
        self.connect_db()
        self.create_tables()
        
        # Get all brands
        brands = self.get_brands()
        
        if max_brands:
            brands = brands[:max_brands]
        
        total_devices = 0
        
        for i, (brand_name, brand_url) in enumerate(brands, 1):
            print(f"\n{'='*60}")
            print(f"[{i}/{len(brands)}] Processing brand: {brand_name}")
            print(f"{'='*60}")
            
            # Extract actual brand name from page
            actual_brand_name = self.extract_brand_name_from_page(brand_url)
            if actual_brand_name:
                brand_name = actual_brand_name
                print(f"  ✓ Extracted brand name from page: {brand_name}")
            else:
                print(f"  ⚠ Using brand name from menu: {brand_name}")
            
            # Save brand
            brand_id = self.save_brand(brand_name, brand_url)
            if not brand_id:
                continue
            
            # Get devices with pagination
            devices = self.get_brand_devices_with_pagination(brand_url)
            
            if max_devices_per_brand:
                devices = devices[:max_devices_per_brand]
            
            # Scrape each device
            for j, (device_name, device_url) in enumerate(devices, 1):
                print(f"\n  [{j}/{len(devices)}]")
                device_id = self.scrape_device(device_name, device_url, brand_id)
                
                if device_id:
                    total_devices += 1
            
            # Extra pause between brands
            if i < len(brands):
                print(f"\n  ⏸ Pausing 30 seconds before next brand...")
                time.sleep(30)
        
        print(f"\n✅ Full scraping completed! Total devices scraped: {total_devices}")
    
    def debug_device_page(self, device_url):
        """Debug method to inspect a device page structure"""
        print(f"\n🔍 Debugging device page: {device_url}\n")
        
        response = self._make_request(device_url, "debug page")
        if not response:
            print("✗ Failed to fetch page")
            return
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for specs-list
        specs_list = soup.find('div', id='specs-list')
        print(f"specs-list found: {specs_list is not None}")
        
        # Check for tables
        if specs_list:
            tables = specs_list.find_all('table', cellspacing='0')
            print(f"Number of spec tables: {len(tables)}")
            
            if tables:
                print("\nFirst table structure:")
                first_table = tables[0]
                rows = first_table.find_all('tr')
                print(f"  Number of rows: {len(rows)}")
                
                for i, row in enumerate(rows[:3]):
                    th = row.find('th')
                    ttl = row.find('td', class_='ttl')
                    nfo = row.find('td', class_='nfo')
                    print(f"  Row {i}: th={th is not None}, ttl={ttl is not None}, nfo={nfo is not None}")
        
        # Check for images
        center_stage = soup.find('div', class_='center-stage')
        print(f"\ncenter-stage found: {center_stage is not None}")
        
        if center_stage:
            main_img = center_stage.find('div', class_='specs-photo-main')
            print(f"specs-photo-main found: {main_img is not None}")
            if main_img:
                img = main_img.find('img')
                print(f"img tag found: {img is not None}")
                if img:
                    print(f"img src: {img.get('src')}")
        
        # Save sample HTML for inspection
        with open('debug_page.html', 'w', encoding='utf-8') as f:
            f.write(str(soup.prettify()))
        print("\n✓ Full page HTML saved to 'debug_page.html'")
    
    def close(self):
        """Close database connection"""
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
        print("\n✓ Database connection closed")


if __name__ == "__main__":
    # Configure delay between requests (in seconds)
    # Increase this value if you're getting blocked
    DELAY_BETWEEN_REQUESTS = 20  # 20 seconds between each page request
    
    scraper = GSMArenaScraper(delay_between_requests=DELAY_BETWEEN_REQUESTS)
    
    try:
        # OPTION 1: Scrape only a specific brand (with pagination)
        url = input('Enter brand URL to scrape (e.g., https://www.gsmarena.com/samsung-phones-9.php): ').strip()
        scraper.scrape_brand(url)  # Remove max_devices to scrape all
        
        # OPTION 2: For testing, limit devices
        # scraper.scrape_brand(url, max_devices=10)
        
        # OPTION 3: Scrape all brands (will take many hours!)
        # scraper.scrape_all()
        
        # OPTION 4: Test with limited brands and devices
        # scraper.scrape_all(max_brands=2, max_devices_per_brand=5)
        
    except KeyboardInterrupt:
        print("\n\n⚠ Scraping interrupted by user")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
    finally:
        scraper.close()