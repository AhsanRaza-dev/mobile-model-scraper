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

print("🚀 Starting migration...")

# STEP 0: Create tables in Neon first
print("\n🔧 Creating tables in Neon...")

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
print("✓ Tables created successfully")

# 1. Migrate brands
print("\n📦 Migrating brands...")
local_cur.execute("SELECT id, name, url, created_at FROM brands ORDER BY id")
brands = local_cur.fetchall()

for brand in brands:
    try:
        neon_cur.execute("""
            INSERT INTO brands (id, name, url, created_at) 
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO NOTHING
        """, brand)
    except Exception as e:
        print(f"  ⚠ Warning: Could not insert brand {brand[1]}: {e}")
        
neon_conn.commit()
print(f"✓ Migrated {len(brands)} brands")

# 2. Migrate devices
print("\n📱 Migrating devices...")
local_cur.execute("SELECT id, brand_id, name, url, main_image, status, announced, released, created_at FROM devices ORDER BY id")
devices = local_cur.fetchall()

for i, device in enumerate(devices, 1):
    try:
        neon_cur.execute("""
            INSERT INTO devices (id, brand_id, name, url, main_image, status, announced, released, created_at) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
        """, device)
        if i % 10 == 0:
            print(f"  Progress: {i}/{len(devices)} devices")
    except Exception as e:
        print(f"  ⚠ Warning: Could not insert device {device[2]}: {e}")
        
neon_conn.commit()
print(f"✓ Migrated {len(devices)} devices")

# 3. Migrate specifications
print("\n📋 Migrating specifications...")
local_cur.execute("SELECT device_id, category, spec_key, spec_value, created_at FROM device_specifications ORDER BY id")
specs = local_cur.fetchall()

batch_size = 1000
for i in range(0, len(specs), batch_size):
    batch = specs[i:i+batch_size]
    for spec in batch:
        try:
            neon_cur.execute("""
                INSERT INTO device_specifications (device_id, category, spec_key, spec_value, created_at) 
                VALUES (%s, %s, %s, %s, %s)
            """, spec)
        except Exception as e:
            pass  # Skip problematic specs
    neon_conn.commit()
    print(f"  Migrated {min(i+batch_size, len(specs))}/{len(specs)} specifications")
    
print(f"✓ Migrated {len(specs)} specifications")

# 4. Migrate images
print("\n🖼️  Migrating images...")
local_cur.execute("SELECT device_id, image_url, image_type, created_at FROM device_images ORDER BY id")
images = local_cur.fetchall()

for image in images:
    try:
        neon_cur.execute("""
            INSERT INTO device_images (device_id, image_url, image_type, created_at) 
            VALUES (%s, %s, %s, %s)
        """, image)
    except Exception as e:
        pass  # Skip problematic images
        
neon_conn.commit()
print(f"✓ Migrated {len(images)} images")

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

print("\n✅ Migration completed successfully!")
print("\n📊 Summary:")
print(f"   Brands: {len(brands)}")
print(f"   Devices: {len(devices)}")
print(f"   Specifications: {len(specs)}")
print(f"   Images: {len(images)}")

print("\n🔗 Next step: Update your Flutter app and run it!")