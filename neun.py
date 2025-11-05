import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

# Local PostgreSQL connection
local_conn = psycopg2.connect(
    host='localhost',
    database='mobile_tablet_db',
    user='postgres',
    password='Ah72n):(:',  # UPDATE THIS
    port=5432
)

# Neon connection
neon_conn = psycopg2.connect(
    host='ep-shiny-river-adbg0g0l-pooler.c-2.us-east-1.aws.neon.tech',
    database='neondb',
    user='neondb_owner',
    password='npg_ugwTQk26FjqD',
    port=5432,
    sslmode='require'
)

local_cur = local_conn.cursor()
neon_cur = neon_conn.cursor()

print("🚀 Starting smart migration (only new data)...")

# STEP 0: Create tables in Neon first
print("\n🔧 Creating tables in Neon if they don't exist...")

tables_sql = """
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

neon_cur.execute(tables_sql)
neon_conn.commit()
print("✓ Tables ready")

# 1. Migrate brands (only new ones)
print("\n📦 Migrating brands...")
local_cur.execute("SELECT id, name, url, created_at FROM brands ORDER BY id")
local_brands = local_cur.fetchall()

# Get existing brand names from Neon
neon_cur.execute("SELECT name FROM brands")
existing_brand_names = set(row[0] for row in neon_cur.fetchall())

new_brands = 0
skipped_brands = 0

for brand in local_brands:
    brand_id, brand_name, brand_url, created_at = brand
    
    if brand_name in existing_brand_names:
        skipped_brands += 1
        continue
    
    try:
        neon_cur.execute("""
            INSERT INTO brands (name, url, created_at) 
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING
        """, (brand_name, brand_url, created_at))
        new_brands += 1
    except Exception as e:
        print(f"  ⚠ Warning: Could not insert brand {brand_name}: {e}")
        
neon_conn.commit()
print(f"✓ Added {new_brands} new brands (skipped {skipped_brands} existing)")

# 2. Migrate devices (only new ones)
print("\n📱 Migrating devices...")
local_cur.execute("SELECT id, brand_id, name, url, main_image, status, announced, released, created_at FROM devices ORDER BY id")
local_devices = local_cur.fetchall()

# Get existing device URLs from Neon
neon_cur.execute("SELECT url FROM devices WHERE url IS NOT NULL")
existing_device_urls = set(row[0] for row in neon_cur.fetchall())

# Create a mapping of brand names to IDs in Neon
neon_cur.execute("SELECT id, name FROM brands")
neon_brand_map = {name: id for id, name in neon_cur.fetchall()}

# Get local brand mapping
local_cur.execute("SELECT id, name FROM brands")
local_brand_map = {id: name for id, name in local_cur.fetchall()}

new_devices = 0
skipped_devices = 0

for i, device in enumerate(local_devices, 1):
    device_id, local_brand_id, name, url, main_image, status, announced, released, created_at = device
    
    if url and url in existing_device_urls:
        skipped_devices += 1
        continue
    
    # Map local brand_id to Neon brand_id
    local_brand_name = local_brand_map.get(local_brand_id)
    neon_brand_id = neon_brand_map.get(local_brand_name) if local_brand_name else None
    
    try:
        neon_cur.execute("""
            INSERT INTO devices (brand_id, name, url, main_image, status, announced, released, created_at) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            RETURNING id
        """, (neon_brand_id, name, url, main_image, status, announced, released, created_at))
        
        result = neon_cur.fetchone()
        if result:
            new_devices += 1
            if new_devices % 10 == 0:
                print(f"  Progress: {new_devices} new devices added ({skipped_devices} skipped)")
    except Exception as e:
        print(f"  ⚠ Warning: Could not insert device {name}: {e}")
        
neon_conn.commit()
print(f"✓ Added {new_devices} new devices (skipped {skipped_devices} existing)")

# 3. Migrate specifications (only for new devices)
print("\n📋 Migrating specifications...")

# Get device URL to ID mapping for both databases
local_cur.execute("SELECT id, url FROM devices WHERE url IS NOT NULL")
local_device_map = {url: id for id, url in local_cur.fetchall()}

neon_cur.execute("SELECT id, url FROM devices WHERE url IS NOT NULL")
neon_device_map = {url: id for id, url in neon_cur.fetchall()}

# Get existing specs (device_id, category, spec_key combinations)
neon_cur.execute("SELECT device_id, category, spec_key FROM device_specifications")
existing_specs = set((device_id, category, spec_key) for device_id, category, spec_key in neon_cur.fetchall())

local_cur.execute("""
    SELECT ds.device_id, ds.category, ds.spec_key, ds.spec_value, ds.created_at, d.url
    FROM device_specifications ds
    JOIN devices d ON ds.device_id = d.id
    WHERE d.url IS NOT NULL
    ORDER BY ds.id
""")
local_specs = local_cur.fetchall()

new_specs = 0
skipped_specs = 0
batch_size = 1000
batch = []

for spec in local_specs:
    local_device_id, category, spec_key, spec_value, created_at, device_url = spec
    
    # Map to Neon device ID
    neon_device_id = neon_device_map.get(device_url)
    
    if not neon_device_id:
        skipped_specs += 1
        continue
    
    # Check if this spec already exists
    if (neon_device_id, category, spec_key) in existing_specs:
        skipped_specs += 1
        continue
    
    batch.append((neon_device_id, category, spec_key, spec_value, created_at))
    
    if len(batch) >= batch_size:
        for spec_data in batch:
            try:
                neon_cur.execute("""
                    INSERT INTO device_specifications (device_id, category, spec_key, spec_value, created_at) 
                    VALUES (%s, %s, %s, %s, %s)
                """, spec_data)
                new_specs += 1
            except Exception as e:
                pass
        neon_conn.commit()
        print(f"  Progress: {new_specs} new specs added ({skipped_specs} skipped)")
        batch = []

# Insert remaining batch
if batch:
    for spec_data in batch:
        try:
            neon_cur.execute("""
                INSERT INTO device_specifications (device_id, category, spec_key, spec_value, created_at) 
                VALUES (%s, %s, %s, %s, %s)
            """, spec_data)
            new_specs += 1
        except Exception as e:
            pass
    neon_conn.commit()

print(f"✓ Added {new_specs} new specifications (skipped {skipped_specs} existing)")

# 4. Migrate images (only for new devices)
print("\n🖼️  Migrating images...")

# Get existing images (device_id, image_url combinations)
neon_cur.execute("SELECT device_id, image_url FROM device_images")
existing_images = set((device_id, image_url) for device_id, image_url in neon_cur.fetchall())

local_cur.execute("""
    SELECT di.device_id, di.image_url, di.image_type, di.created_at, d.url
    FROM device_images di
    JOIN devices d ON di.device_id = d.id
    WHERE d.url IS NOT NULL
    ORDER BY di.id
""")
local_images = local_cur.fetchall()

new_images = 0
skipped_images = 0

for image in local_images:
    local_device_id, image_url, image_type, created_at, device_url = image
    
    # Map to Neon device ID
    neon_device_id = neon_device_map.get(device_url)
    
    if not neon_device_id:
        skipped_images += 1
        continue
    
    # Check if this image already exists
    if (neon_device_id, image_url) in existing_images:
        skipped_images += 1
        continue
    
    try:
        neon_cur.execute("""
            INSERT INTO device_images (device_id, image_url, image_type, created_at) 
            VALUES (%s, %s, %s, %s)
        """, (neon_device_id, image_url, image_type, created_at))
        new_images += 1
    except Exception as e:
        pass
        
neon_conn.commit()
print(f"✓ Added {new_images} new images (skipped {skipped_images} existing)")

# Reset sequences to continue from max ID
print("\n🔧 Resetting sequences...")
try:
    neon_cur.execute("SELECT setval('brands_id_seq', (SELECT COALESCE(MAX(id), 1) FROM brands))")
    neon_cur.execute("SELECT setval('devices_id_seq', (SELECT COALESCE(MAX(id), 1) FROM devices))")
    neon_cur.execute("SELECT setval('device_specifications_id_seq', (SELECT COALESCE(MAX(id), 1) FROM device_specifications))")
    neon_cur.execute("SELECT setval('device_images_id_seq', (SELECT COALESCE(MAX(id), 1) FROM device_images))")
    neon_conn.commit()
    print("✓ Sequences reset")
except Exception as e:
    print(f"⚠ Warning: Could not reset sequences: {e}")

# Close connections
local_cur.close()
neon_cur.close()
local_conn.close()
neon_conn.close()

print("\n✅ Smart migration completed successfully!")
print("\n📊 Summary:")
print(f"   Brands: {new_brands} new (skipped {skipped_brands} existing)")
print(f"   Devices: {new_devices} new (skipped {skipped_devices} existing)")
print(f"   Specifications: {new_specs} new (skipped {skipped_specs} existing)")
print(f"   Images: {new_images} new (skipped {skipped_images} existing)")

print("\n🔗 Your Neon database is up to date with only new data!")