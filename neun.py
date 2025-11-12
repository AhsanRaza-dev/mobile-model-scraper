import psycopg2
from dotenv import load_dotenv
import os
import re
from collections import defaultdict

load_dotenv()

class NeonMigrationWithClassification:
    """
    Migrates data from local PostgreSQL to Neon and classifies parent-child relationships
    """
    
    # Variant patterns for classification
    VARIANT_PATTERNS = [
        (r'\s+(FE)$', 'FE'),
        (r'\s+(SE)$', 'SE'),
        (r'\s+(Lite)$', 'Lite'),
        (r'\s+(Plus|\+)$', 'Plus'),
        (r'\s+(Pro\+?)$', 'Pro'),
        (r'\s+(Ultra)$', 'Ultra'),
        (r'\s+(Max)$', 'Max'),
        (r'\s+(Mini)$', 'Mini'),
        (r'(\s+5G)$', '5G'),
        (r'(\s+4G)$', '4G'),
        (r'(\s+LTE)$', 'LTE'),
    ]
    
    def __init__(self):
        self.local_conn = None
        self.neon_conn = None
        self.local_cur = None
        self.neon_cur = None
        
    def connect_databases(self):
        """Connect to both local and Neon databases"""
        print("🔌 Connecting to databases...")
        
        # Local PostgreSQL connection
        self.local_conn = psycopg2.connect(
            host='localhost',
            database='mobile_tablet_db',
            user='postgres',
            password='Ah72n):(:',
            port=5432
        )
        
        # Updated Neon connection with new credentials and keepalive
        self.neon_conn = psycopg2.connect(
            host='ep-round-block-ad0wjhe2-pooler.c-2.us-east-1.aws.neon.tech',
            database='neondb',
            user='neondb_owner',
            password='npg_fA4m6PJtgCLk',
            port=5432,
            sslmode='require',
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
        
        self.local_cur = self.local_conn.cursor()
        self.neon_cur = self.neon_conn.cursor()
        
        print("✓ Connected to both databases")
    
    def ensure_connection(self):
        """Ensure Neon connection is alive, reconnect if needed"""
        try:
            self.neon_cur.execute("SELECT 1")
        except:
            print("   Reconnecting to Neon...")
            if self.neon_cur:
                self.neon_cur.close()
            if self.neon_conn:
                self.neon_conn.close()
            
            self.neon_conn = psycopg2.connect(
                host='ep-round-block-ad0wjhe2-pooler.c-2.us-east-1.aws.neon.tech',
                database='neondb',
                user='neondb_owner',
                password='npg_fA4m6PJtgCLk',
                port=5432,
                sslmode='require',
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )
            self.neon_cur = self.neon_conn.cursor()
            print("   ✓ Reconnected")
    
    def create_tables_with_classification(self):
        """Create tables in Neon with parent-child relationship columns"""
        print("\n🔧 Creating tables with classification support...")
        
        # Create base tables first
        base_tables_sql = """
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
        """
        
        self.neon_cur.execute(base_tables_sql)
        self.neon_conn.commit()
        
        # Add classification columns to existing devices table
        print("   Adding classification columns...")
        
        # Check and add parent_id column
        try:
            self.neon_cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='devices' AND column_name='parent_id'
            """)
            if not self.neon_cur.fetchone():
                print("      Adding parent_id column...")
                self.neon_cur.execute("""
                    ALTER TABLE devices 
                    ADD COLUMN parent_id INTEGER REFERENCES devices(id) ON DELETE SET NULL
                """)
                self.neon_conn.commit()
            else:
                print("      parent_id column exists ✓")
        except Exception as e:
            print(f"      parent_id error: {e}")
            self.neon_conn.rollback()
        
        # Check and add is_parent column
        try:
            self.neon_cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='devices' AND column_name='is_parent'
            """)
            if not self.neon_cur.fetchone():
                print("      Adding is_parent column...")
                self.neon_cur.execute("""
                    ALTER TABLE devices 
                    ADD COLUMN is_parent BOOLEAN DEFAULT TRUE
                """)
                self.neon_conn.commit()
            else:
                print("      is_parent column exists ✓")
        except Exception as e:
            print(f"      is_parent error: {e}")
            self.neon_conn.rollback()
        
        # Check and add variant_suffix column
        try:
            self.neon_cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='devices' AND column_name='variant_suffix'
            """)
            if not self.neon_cur.fetchone():
                print("      Adding variant_suffix column...")
                self.neon_cur.execute("""
                    ALTER TABLE devices 
                    ADD COLUMN variant_suffix VARCHAR(50)
                """)
                self.neon_conn.commit()
            else:
                print("      variant_suffix column exists ✓")
        except Exception as e:
            print(f"      variant_suffix error: {e}")
            self.neon_conn.rollback()
        
        # Create indexes (only create index if column exists)
        print("   Creating indexes...")
        
        # Check if is_parent column exists before creating index
        self.neon_cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='devices' AND column_name='is_parent'
        """)
        
        if self.neon_cur.fetchone():
            try:
                self.neon_cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_brand ON devices(brand_id)")
                self.neon_cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_parent_id ON devices(parent_id)")
                self.neon_cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_is_parent ON devices(is_parent)")
                self.neon_cur.execute("CREATE INDEX IF NOT EXISTS idx_specs_device ON device_specifications(device_id)")
                self.neon_cur.execute("CREATE INDEX IF NOT EXISTS idx_images_device ON device_images(device_id)")
                self.neon_conn.commit()
                print("      Indexes created ✓")
            except Exception as e:
                print(f"      Index creation note: {e}")
                self.neon_conn.rollback()
        else:
            print("      Skipping indexes - columns not ready yet")
        
        print("✓ Tables ready with classification columns")
    
    def clear_all_data(self):
        """Clear all existing data from Neon database"""
        print("\n🗑️  Clearing existing data from Neon...")
        
        try:
            # Drop tables in correct order (respecting foreign keys)
            self.neon_cur.execute("""
                DROP TABLE IF EXISTS device_images CASCADE;
                DROP TABLE IF EXISTS device_specifications CASCADE;
                DROP TABLE IF EXISTS devices CASCADE;
                DROP TABLE IF EXISTS brands CASCADE;
            """)
            self.neon_conn.commit()
            print("✓ All data cleared")
        except Exception as e:
            print(f"⚠ Error clearing data: {e}")
            self.neon_conn.rollback()
    
    def migrate_brands(self):
        """Migrate brands from local to Neon"""
        print("\n📦 Migrating brands...")
        self.local_cur.execute("SELECT id, name, url, created_at FROM brands ORDER BY id")
        local_brands = self.local_cur.fetchall()
        
        self.neon_cur.execute("SELECT name FROM brands")
        existing_brand_names = set(row[0] for row in self.neon_cur.fetchall())
        
        new_brands = 0
        skipped_brands = 0
        
        for brand in local_brands:
            brand_id, brand_name, brand_url, created_at = brand
            
            if brand_name in existing_brand_names:
                skipped_brands += 1
                continue
            
            try:
                self.neon_cur.execute("""
                    INSERT INTO brands (name, url, created_at) 
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name) DO NOTHING
                """, (brand_name, brand_url, created_at))
                new_brands += 1
            except Exception as e:
                print(f"  ⚠ Warning: Could not insert brand {brand_name}: {e}")
                
        self.neon_conn.commit()
        print(f"✓ Added {new_brands} new brands (skipped {skipped_brands} existing)")
    
    def migrate_devices(self):
        """Migrate devices from local to Neon"""
        print("\n📱 Migrating devices...")
        self.local_cur.execute("""
            SELECT id, brand_id, name, url, main_image, status, announced, released, created_at 
            FROM devices ORDER BY id
        """)
        local_devices = self.local_cur.fetchall()
        
        self.neon_cur.execute("SELECT url FROM devices WHERE url IS NOT NULL")
        existing_device_urls = set(row[0] for row in self.neon_cur.fetchall())
        
        self.neon_cur.execute("SELECT id, name FROM brands")
        neon_brand_map = {name: id for id, name in self.neon_cur.fetchall()}
        
        self.local_cur.execute("SELECT id, name FROM brands")
        local_brand_map = {id: name for id, name in self.local_cur.fetchall()}
        
        new_devices = 0
        skipped_devices = 0
        
        for device in local_devices:
            device_id, local_brand_id, name, url, main_image, status, announced, released, created_at = device
            
            if url and url in existing_device_urls:
                skipped_devices += 1
                continue
            
            local_brand_name = local_brand_map.get(local_brand_id)
            neon_brand_id = neon_brand_map.get(local_brand_name) if local_brand_name else None
            
            try:
                self.neon_cur.execute("""
                    INSERT INTO devices (brand_id, name, url, main_image, status, announced, released, created_at) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                    RETURNING id
                """, (neon_brand_id, name, url, main_image, status, announced, released, created_at))
                
                result = self.neon_cur.fetchone()
                if result:
                    new_devices += 1
                    if new_devices % 100 == 0:
                        print(f"  Progress: {new_devices} new devices added")
            except Exception as e:
                print(f"  ⚠ Warning: Could not insert device {name}: {e}")
                
        self.neon_conn.commit()
        print(f"✓ Added {new_devices} new devices (skipped {skipped_devices} existing)")
    
    def migrate_specifications(self):
        """Migrate specifications from local to Neon"""
        print("\n📋 Migrating specifications...")
        
        self.local_cur.execute("SELECT id, url FROM devices WHERE url IS NOT NULL")
        local_device_map = {url: id for id, url in self.local_cur.fetchall()}
        
        self.neon_cur.execute("SELECT id, url FROM devices WHERE url IS NOT NULL")
        neon_device_map = {url: id for id, url in self.neon_cur.fetchall()}
        
        self.neon_cur.execute("SELECT device_id, category, spec_key FROM device_specifications")
        existing_specs = set((device_id, category, spec_key) 
                            for device_id, category, spec_key in self.neon_cur.fetchall())
        
        self.local_cur.execute("""
            SELECT ds.device_id, ds.category, ds.spec_key, ds.spec_value, ds.created_at, d.url
            FROM device_specifications ds
            JOIN devices d ON ds.device_id = d.id
            WHERE d.url IS NOT NULL
            ORDER BY ds.id
        """)
        local_specs = self.local_cur.fetchall()
        
        new_specs = 0
        skipped_specs = 0
        batch = []
        batch_size = 500  # Reduced batch size for more frequent commits
        
        for spec in local_specs:
            local_device_id, category, spec_key, spec_value, created_at, device_url = spec
            
            neon_device_id = neon_device_map.get(device_url)
            
            if not neon_device_id or (neon_device_id, category, spec_key) in existing_specs:
                skipped_specs += 1
                continue
            
            batch.append((neon_device_id, category, spec_key, spec_value, created_at))
            
            if len(batch) >= batch_size:
                # Ensure connection is alive before batch insert
                self.ensure_connection()
                
                for spec_data in batch:
                    try:
                        self.neon_cur.execute("""
                            INSERT INTO device_specifications 
                            (device_id, category, spec_key, spec_value, created_at) 
                            VALUES (%s, %s, %s, %s, %s)
                        """, spec_data)
                        new_specs += 1
                    except:
                        pass
                
                self.neon_conn.commit()
                
                if new_specs % 5000 == 0:
                    print(f"  Progress: {new_specs} specs added")
                
                batch = []
        
        # Insert remaining batch
        if batch:
            self.ensure_connection()
            
            for spec_data in batch:
                try:
                    self.neon_cur.execute("""
                        INSERT INTO device_specifications 
                        (device_id, category, spec_key, spec_value, created_at) 
                        VALUES (%s, %s, %s, %s, %s)
                    """, spec_data)
                    new_specs += 1
                except:
                    pass
            self.neon_conn.commit()
        
        print(f"✓ Added {new_specs} specifications (skipped {skipped_specs})")
    
    def migrate_images(self):
        """Migrate images from local to Neon"""
        print("\n🖼️  Migrating images...")
        
        self.neon_cur.execute("SELECT id, url FROM devices WHERE url IS NOT NULL")
        neon_device_map = {url: id for id, url in self.neon_cur.fetchall()}
        
        self.neon_cur.execute("SELECT device_id, image_url FROM device_images")
        existing_images = set((device_id, image_url) 
                             for device_id, image_url in self.neon_cur.fetchall())
        
        self.local_cur.execute("""
            SELECT di.device_id, di.image_url, di.image_type, di.created_at, d.url
            FROM device_images di
            JOIN devices d ON di.device_id = d.id
            WHERE d.url IS NOT NULL
            ORDER BY di.id
        """)
        local_images = self.local_cur.fetchall()
        
        new_images = 0
        skipped_images = 0
        
        for image in local_images:
            local_device_id, image_url, image_type, created_at, device_url = image
            
            neon_device_id = neon_device_map.get(device_url)
            
            if not neon_device_id or (neon_device_id, image_url) in existing_images:
                skipped_images += 1
                continue
            
            try:
                self.neon_cur.execute("""
                    INSERT INTO device_images (device_id, image_url, image_type, created_at) 
                    VALUES (%s, %s, %s, %s)
                """, (neon_device_id, image_url, image_type, created_at))
                new_images += 1
            except:
                pass
                
        self.neon_conn.commit()
        print(f"✓ Added {new_images} images (skipped {skipped_images})")
    
    def has_model_identifier(self, name):
        """Check if device name has a clear model identifier"""
        parts = name.split()
        name_without_brand = ' '.join(parts[1:]) if len(parts) > 1 else name
        has_model = bool(re.search(r'[A-Z]\d+|Tab\s+[A-Z]\d+|Fold\d+|Flip\d+', name_without_brand))
        return has_model
    
    def extract_variant(self, device_name):
        """Extract variant suffix from device name with strict rules"""
        name = device_name.strip()
        
        if not self.has_model_identifier(name):
            return {
                'full_name': device_name,
                'parent_name': device_name,
                'variant': None,
                'is_parent': True
            }
        
        for pattern, variant_name in self.VARIANT_PATTERNS:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                parent_name = name[:match.start()].strip()
                
                if self.has_model_identifier(parent_name):
                    return {
                        'full_name': device_name,
                        'parent_name': parent_name,
                        'variant': variant_name,
                        'is_parent': False
                    }
        
        return {
            'full_name': device_name,
            'parent_name': device_name,
            'variant': None,
            'is_parent': True
        }
    
    def classify_devices(self):
        """Classify devices into parent-child relationships"""
        print("\n🔗 Classifying parent-child relationships...")
        
        self.neon_cur.execute("""
            SELECT d.id, d.name, d.brand_id, b.name as brand_name
            FROM devices d
            JOIN brands b ON d.brand_id = b.id
            ORDER BY b.name, d.name
        """)
        devices = self.neon_cur.fetchall()
        
        print(f"   Analyzing {len(devices)} devices...")
        
        # Classify all devices
        classified = {}
        parent_map = defaultdict(list)
        
        for device_id, device_name, brand_id, brand in devices:
            classification = self.extract_variant(device_name)
            classification['device_id'] = device_id
            classification['brand'] = brand
            classified[device_id] = classification
            
            parent_name = classification['parent_name']
            parent_map[parent_name].append(device_id)
        
        # Identify true parents
        true_parents = {}
        for parent_name, device_ids in parent_map.items():
            for device_id in device_ids:
                if classified[device_id]['full_name'] == parent_name:
                    true_parents[parent_name] = device_id
                    break
        
        # Group by family
        families = defaultdict(list)
        for device_id, info in classified.items():
            families[info['parent_name']].append(info)
        
        # Count relationships
        parent_count = 0
        child_count = 0
        
        for parent_name, members in families.items():
            if len(members) > 1:
                for member in members:
                    if member['full_name'] == parent_name:
                        parent_count += 1
                    else:
                        child_count += 1
        
        print(f"   Found {parent_count} parents with {child_count} children")
        
        # Update database
        print("   Updating database...")
        updated = 0
        
        for device_id, info in classified.items():
            try:
                if info['full_name'] == info['parent_name']:
                    has_children = len(families[info['parent_name']]) > 1
                    
                    self.neon_cur.execute("""
                        UPDATE devices
                        SET parent_id = NULL,
                            is_parent = %s,
                            variant_suffix = NULL
                        WHERE id = %s
                    """, (has_children, device_id))
                else:
                    parent_id = true_parents.get(info['parent_name'])
                    
                    if parent_id:
                        self.neon_cur.execute("""
                            UPDATE devices
                            SET parent_id = %s,
                                is_parent = FALSE,
                                variant_suffix = %s
                            WHERE id = %s
                        """, (parent_id, info['variant'], device_id))
                    else:
                        self.neon_cur.execute("""
                            UPDATE devices
                            SET parent_id = NULL,
                                is_parent = TRUE,
                                variant_suffix = NULL
                            WHERE id = %s
                        """, (device_id,))
                
                updated += 1
                if updated % 500 == 0:
                    print(f"   Progress: {updated}/{len(devices)}")
                    
            except Exception as e:
                print(f"   ⚠ Error updating device {info['full_name']}: {e}")
        
        self.neon_conn.commit()
        print(f"✓ Classification complete: {parent_count} parents, {child_count} children")
    
    def reset_sequences(self):
        """Reset auto-increment sequences"""
        print("\n🔧 Resetting sequences...")
        try:
            self.neon_cur.execute("SELECT setval('brands_id_seq', (SELECT COALESCE(MAX(id), 1) FROM brands))")
            self.neon_cur.execute("SELECT setval('devices_id_seq', (SELECT COALESCE(MAX(id), 1) FROM devices))")
            self.neon_cur.execute("SELECT setval('device_specifications_id_seq', (SELECT COALESCE(MAX(id), 1) FROM device_specifications))")
            self.neon_cur.execute("SELECT setval('device_images_id_seq', (SELECT COALESCE(MAX(id), 1) FROM device_images))")
            self.neon_conn.commit()
            print("✓ Sequences reset")
        except Exception as e:
            print(f"⚠ Warning: {e}")
    
    def show_summary(self):
        """Display final summary"""
        print("\n" + "="*80)
        print("📊 MIGRATION SUMMARY")
        print("="*80)
        
        self.neon_cur.execute("SELECT COUNT(*) FROM brands")
        brand_count = self.neon_cur.fetchone()[0]
        
        self.neon_cur.execute("SELECT COUNT(*) FROM devices")
        device_count = self.neon_cur.fetchone()[0]
        
        self.neon_cur.execute("SELECT COUNT(*) FROM devices WHERE is_parent = TRUE AND parent_id IS NULL")
        parent_count = self.neon_cur.fetchone()[0]
        
        self.neon_cur.execute("SELECT COUNT(*) FROM devices WHERE parent_id IS NOT NULL")
        child_count = self.neon_cur.fetchone()[0]
        
        self.neon_cur.execute("SELECT COUNT(*) FROM device_specifications")
        spec_count = self.neon_cur.fetchone()[0]
        
        self.neon_cur.execute("SELECT COUNT(*) FROM device_images")
        image_count = self.neon_cur.fetchone()[0]
        
        print(f"Total Brands: {brand_count}")
        print(f"Total Devices: {device_count}")
        print(f"  - Parent devices: {parent_count}")
        print(f"  - Child variants: {child_count}")
        print(f"Total Specifications: {spec_count}")
        print(f"Total Images: {image_count}")
        print("="*80)
    
    def close(self):
        """Close database connections"""
        if self.local_cur:
            self.local_cur.close()
        if self.neon_cur:
            self.neon_cur.close()
        if self.local_conn:
            self.local_conn.close()
        if self.neon_conn:
            self.neon_conn.close()
        print("\n✓ Database connections closed")


def main():
    """Main execution"""
    migrator = NeonMigrationWithClassification()
    
    try:
        print("="*80)
        print("🚀 NEON MIGRATION WITH PARENT-CHILD CLASSIFICATION")
        print("="*80)
        
        # Ask if user wants to clear existing data
        print("\n⚠️  WARNING: This will clear ALL existing data in Neon database!")
        clear_data = input("Do you want to clear existing data first? (yes/no): ").strip().lower()
        
        migrator.connect_databases()
        
        if clear_data in ['yes', 'y']:
            migrator.clear_all_data()
        
        migrator.create_tables_with_classification()
        migrator.migrate_brands()
        migrator.migrate_devices()
        migrator.migrate_specifications()
        migrator.migrate_images()
        migrator.classify_devices()
        migrator.reset_sequences()
        migrator.show_summary()
        
        print("\n✅ Migration and classification completed successfully!")
        print("🔗 Your Neon database is ready with parent-child relationships!")
        
    except KeyboardInterrupt:
        print("\n\n⚠ Operation cancelled by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        migrator.close()


if __name__ == "__main__":
    main()