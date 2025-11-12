import psycopg2
import sqlite3
import os
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

class DatabaseExporter:
    """Export PostgreSQL data to SQLite for local Flutter app usage"""
    
    def __init__(self, output_file='phone_specs.db'):
        self.output_file = output_file
        self.pg_conn = None
        self.sqlite_conn = None
        
    def connect_postgres(self):
        """Connect to PostgreSQL database"""
        try:
            self.pg_conn = psycopg2.connect(
                host=os.getenv('DB_HOST'),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                port=os.getenv('DB_PORT', 5432)
            )
            print("✓ Connected to PostgreSQL")
        except Exception as e:
            print(f"✗ PostgreSQL connection error: {e}")
            raise
    
    def create_sqlite_database(self):
        """Create SQLite database with schema"""
        try:
            # Remove existing database
            if os.path.exists(self.output_file):
                os.remove(self.output_file)
                print(f"✓ Removed existing {self.output_file}")
            
            self.sqlite_conn = sqlite3.connect(self.output_file)
            cursor = self.sqlite_conn.cursor()
            
            # Create tables
            cursor.executescript("""
                -- Brands table
                CREATE TABLE brands (
                    id INTEGER PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    url TEXT,
                    device_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Devices table
                CREATE TABLE devices (
                    id INTEGER PRIMARY KEY,
                    brand_id INTEGER,
                    name TEXT NOT NULL,
                    url TEXT UNIQUE,
                    main_image TEXT,
                    status TEXT,
                    announced TEXT,
                    released TEXT,
                    parent_id INTEGER,
                    is_parent INTEGER DEFAULT 1,
                    variant_suffix TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (brand_id) REFERENCES brands(id),
                    FOREIGN KEY (parent_id) REFERENCES devices(id)
                );
                
                -- Device specifications table
                CREATE TABLE device_specifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id INTEGER,
                    category TEXT,
                    spec_key TEXT,
                    spec_value TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                );
                
                -- Device images table
                CREATE TABLE device_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id INTEGER,
                    image_url TEXT,
                    image_type TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                );
                
                -- Indexes for performance
                CREATE INDEX idx_devices_brand ON devices(brand_id);
                CREATE INDEX idx_devices_parent ON devices(parent_id);
                CREATE INDEX idx_devices_is_parent ON devices(is_parent);
                CREATE INDEX idx_specs_device ON device_specifications(device_id);
                CREATE INDEX idx_images_device ON device_images(device_id);
                CREATE INDEX idx_devices_name ON devices(name);
                CREATE INDEX idx_brands_name ON brands(name);
            """)
            
            self.sqlite_conn.commit()
            print("✓ SQLite database schema created")
            
        except Exception as e:
            print(f"✗ Error creating SQLite database: {e}")
            raise
    
    def export_brands(self):
        """Export brands from PostgreSQL to SQLite with device counts"""
        print("\n📦 Exporting brands...")
        
        pg_cursor = self.pg_conn.cursor()
        sqlite_cursor = self.sqlite_conn.cursor()
        
        # Get brands with device counts from PostgreSQL
        pg_cursor.execute("""
            SELECT 
                b.id, 
                b.name, 
                b.url, 
                b.created_at,
                COUNT(d.id) as device_count
            FROM brands b
            LEFT JOIN devices d ON b.id = d.brand_id
            GROUP BY b.id, b.name, b.url, b.created_at
            ORDER BY b.id
        """)
        brands = pg_cursor.fetchall()
        
        # Insert into SQLite
        sqlite_cursor.executemany(
            "INSERT INTO brands (id, name, url, created_at, device_count) VALUES (?, ?, ?, ?, ?)",
            brands
        )
        
        self.sqlite_conn.commit()
        print(f"✓ Exported {len(brands)} brands")
        
        return len(brands)
    
    def export_devices(self):
        """Export devices from PostgreSQL to SQLite"""
        print("\n📱 Exporting devices...")
        
        pg_cursor = self.pg_conn.cursor()
        sqlite_cursor = self.sqlite_conn.cursor()
        
        # Get devices from PostgreSQL
        pg_cursor.execute("""
            SELECT id, brand_id, name, url, main_image, status, announced, released,
                   parent_id, is_parent, variant_suffix, created_at
            FROM devices
            ORDER BY id
        """)
        
        devices = pg_cursor.fetchall()
        
        # Insert into SQLite with progress bar
        for device in tqdm(devices, desc="Devices"):
            sqlite_cursor.execute("""
                INSERT INTO devices 
                (id, brand_id, name, url, main_image, status, announced, released,
                 parent_id, is_parent, variant_suffix, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, device)
        
        self.sqlite_conn.commit()
        print(f"✓ Exported {len(devices)} devices")
        
        return len(devices)
    
    def export_specifications(self):
        """Export device specifications from PostgreSQL to SQLite"""
        print("\n📋 Exporting specifications...")
        
        pg_cursor = self.pg_conn.cursor()
        sqlite_cursor = self.sqlite_conn.cursor()
        
        # Get specifications from PostgreSQL
        pg_cursor.execute("""
            SELECT device_id, category, spec_key, spec_value
            FROM device_specifications
            ORDER BY device_id, id
        """)
        
        specs = pg_cursor.fetchall()
        
        # Insert into SQLite with progress bar
        batch_size = 1000
        for i in tqdm(range(0, len(specs), batch_size), desc="Specifications"):
            batch = specs[i:i + batch_size]
            sqlite_cursor.executemany("""
                INSERT INTO device_specifications 
                (device_id, category, spec_key, spec_value)
                VALUES (?, ?, ?, ?)
            """, batch)
            self.sqlite_conn.commit()
        
        print(f"✓ Exported {len(specs)} specifications")
        
        return len(specs)
    
    def export_images(self):
        """Export device images from PostgreSQL to SQLite"""
        print("\n🖼️  Exporting images...")
        
        pg_cursor = self.pg_conn.cursor()
        sqlite_cursor = self.sqlite_conn.cursor()
        
        # Get images from PostgreSQL
        pg_cursor.execute("""
            SELECT device_id, image_url, image_type
            FROM device_images
            ORDER BY device_id, id
        """)
        
        images = pg_cursor.fetchall()
        
        # Insert into SQLite with progress bar
        batch_size = 1000
        for i in tqdm(range(0, len(images), batch_size), desc="Images"):
            batch = images[i:i + batch_size]
            sqlite_cursor.executemany("""
                INSERT INTO device_images 
                (device_id, image_url, image_type)
                VALUES (?, ?, ?)
            """, batch)
            self.sqlite_conn.commit()
        
        print(f"✓ Exported {len(images)} image records")
        
        return len(images)
    
    def get_database_stats(self):
        """Get statistics about the exported database"""
        cursor = self.sqlite_conn.cursor()
        
        stats = {}
        
        # Get counts
        cursor.execute("SELECT COUNT(*) FROM brands")
        stats['brands'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM devices")
        stats['devices'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM devices WHERE is_parent = 1")
        stats['parent_devices'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM devices WHERE parent_id IS NOT NULL")
        stats['child_devices'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM device_specifications")
        stats['specifications'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM device_images")
        stats['images'] = cursor.fetchone()[0]
        
        # Get file size
        stats['file_size_mb'] = os.path.getsize(self.output_file) / (1024 * 1024)
        
        return stats
    
    def export_all(self):
        """Export all data from PostgreSQL to SQLite"""
        try:
            print("🚀 Starting database export from PostgreSQL to SQLite\n")
            print("="*60)
            
            # Connect to databases
            self.connect_postgres()
            self.create_sqlite_database()
            
            # Export all tables
            self.export_brands()
            self.export_devices()
            self.export_specifications()
            self.export_images()
            
            # Get and display statistics
            print("\n" + "="*60)
            print("📊 EXPORT SUMMARY")
            print("="*60)
            
            stats = self.get_database_stats()
            
            print(f"\n✓ Database file: {self.output_file}")
            print(f"  File size: {stats['file_size_mb']:.2f} MB")
            print(f"\n  📦 Brands: {stats['brands']}")
            print(f"  📱 Total Devices: {stats['devices']}")
            print(f"     ├── Parent Devices: {stats['parent_devices']}")
            print(f"     └── Variant Devices: {stats['child_devices']}")
            print(f"  📋 Specifications: {stats['specifications']}")
            print(f"  🖼️  Images: {stats['images']}")
            
            print("\n✅ Export completed successfully!")
            print("="*60)
            print(f"\n💡 Next steps:")
            print(f"   1. Copy '{self.output_file}' to your Flutter project's assets folder")
            print(f"   2. Update pubspec.yaml to include the database file")
            print(f"   3. Use sqflite package to access the local database")
            
        except Exception as e:
            print(f"\n✗ Export failed: {e}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            self.close()
    
    def optimize_database(self):
        """Optimize SQLite database for better performance"""
        print("\n🔧 Optimizing database...")
        
        cursor = self.sqlite_conn.cursor()
        
        # Analyze database for query optimization
        cursor.execute("ANALYZE")
        
        # Vacuum to reclaim unused space
        cursor.execute("VACUUM")
        
        self.sqlite_conn.commit()
        print("✓ Database optimized")
    
    def verify_export(self):
        """Verify that all data was exported correctly"""
        print("\n🔍 Verifying export...")
        
        pg_cursor = self.pg_conn.cursor()
        sqlite_cursor = self.sqlite_conn.cursor()
        
        tables = ['brands', 'devices', 'device_specifications', 'device_images']
        all_match = True
        
        for table in tables:
            # Get count from PostgreSQL
            pg_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            pg_count = pg_cursor.fetchone()[0]
            
            # Get count from SQLite
            sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            sqlite_count = sqlite_cursor.fetchone()[0]
            
            match = "✓" if pg_count == sqlite_count else "✗"
            print(f"  {match} {table}: PostgreSQL={pg_count}, SQLite={sqlite_count}")
            
            if pg_count != sqlite_count:
                all_match = False
        
        if all_match:
            print("\n✓ All data verified successfully!")
        else:
            print("\n⚠ Warning: Some counts don't match. Please review.")
        
        return all_match
    
    def close(self):
        """Close database connections"""
        if self.pg_conn:
            self.pg_conn.close()
        if self.sqlite_conn:
            self.sqlite_conn.close()
        print("\n✓ Database connections closed")


def main():
    """Main execution function with options"""
    print("="*60)
    print("PHONE SPECS DATABASE EXPORTER")
    print("PostgreSQL → SQLite")
    print("="*60)
    
    # Get user options
    output_file = input("\nOutput filename [phone_specs.db]: ").strip()
    if not output_file:
        output_file = 'phone_specs.db'
    
    optimize = input("Optimize database after export? (y/n) [y]: ").strip().lower()
    if not optimize or optimize == 'y':
        optimize = True
    else:
        optimize = False
    
    verify = input("Verify export integrity? (y/n) [y]: ").strip().lower()
    if not verify or verify == 'y':
        verify = True
    else:
        verify = False
    
    # Create exporter and run
    exporter = DatabaseExporter(output_file=output_file)
    
    try:
        exporter.export_all()
        
        if verify:
            exporter.verify_export()
        
        if optimize:
            exporter.optimize_database()
        
        # Final size check
        final_size = os.path.getsize(output_file) / (1024 * 1024)
        print(f"\n📊 Final database size: {final_size:.2f} MB")
        
        print("\n" + "="*60)
        print("🎉 EXPORT COMPLETED SUCCESSFULLY!")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n⚠ Export interrupted by user")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        exporter.close()


if __name__ == "__main__":
    main()