import psycopg2
from dotenv import load_dotenv
import os
import re
from collections import defaultdict

load_dotenv()

class ParentChildClassifier:
    """
    Classifies devices into parent-child relationships with STRICT matching.
    Only creates relationships when model names match EXACTLY.
    """
    
    # Variant patterns - must come AFTER a complete model name
    VARIANT_PATTERNS = [
        # Model edition variants - most specific first
        (r'\s+(FE)$', 'FE'),
        (r'\s+(SE)$', 'SE'),
        (r'\s+(Lite)$', 'Lite'),
        (r'\s+(Plus|\+)$', 'Plus'),
        (r'\s+(Pro\+?)$', 'Pro'),
        (r'\s+(Ultra)$', 'Ultra'),
        (r'\s+(Max)$', 'Max'),
        (r'\s+(Mini)$', 'Mini'),
        
        # Network variants - ONLY if they come after model number/name
        (r'(\s+5G)$', '5G'),
        (r'(\s+4G)$', '4G'),
        (r'(\s+LTE)$', 'LTE'),
    ]
    
    def __init__(self):
        self.conn = None
        self.cur = None
    
    def connect_db(self):
        """Connect to PostgreSQL database"""
        try:
            self.conn = psycopg2.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                port=os.getenv('DB_PORT', 5432)
            )
            self.cur = self.conn.cursor()
            print("✓ Connected to database")
        except Exception as e:
            print(f"✗ Database connection error: {e}")
            raise
    
    def setup_parent_child_structure(self):
        """Add parent-child relationship columns to devices table"""
        try:
            print("\n🔧 Setting up parent-child relationship structure...")
            
            self.cur.execute("""
                -- Add parent_id column to create relationship
                ALTER TABLE devices 
                ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS is_parent BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS variant_suffix VARCHAR(50);
                
                -- Create indexes for performance
                CREATE INDEX IF NOT EXISTS idx_devices_parent_id ON devices(parent_id);
                CREATE INDEX IF NOT EXISTS idx_devices_is_parent ON devices(is_parent);
            """)
            
            self.conn.commit()
            print("✓ Parent-child structure created")
        except Exception as e:
            print(f"✗ Error setting up structure: {e}")
            self.conn.rollback()
            raise
    
    def has_model_identifier(self, name):
        """
        Check if name has a clear model identifier (number or specific model name).
        This helps distinguish 'Galaxy Tab Ultra' (model) from 'Galaxy Tab S9 Ultra' (variant)
        """
        # Remove brand name
        parts = name.split()
        if len(parts) > 1:
            name_without_brand = ' '.join(parts[1:])
        else:
            name_without_brand = name
        
        # Check if there's a model number or letter+number combination
        # E.g., "S24", "A15", "M51", "Tab S9", "Z Fold6"
        has_model = bool(re.search(r'[A-Z]\d+|Tab\s+[A-Z]\d+|Fold\d+|Flip\d+', name_without_brand))
        
        return has_model
    
    def extract_variant(self, device_name):
        """
        Extract variant suffix from device name with STRICT rules.
        Only matches if:
        1. The base name has a clear model identifier (number)
        2. The variant comes at the END of the name
        """
        name = device_name.strip()
        
        # First check if this name has a model identifier
        if not self.has_model_identifier(name):
            # No clear model identifier - treat as parent (e.g., "Galaxy Tab Ultra" is its own model)
            return {
                'full_name': device_name,
                'parent_name': device_name,
                'variant': None,
                'is_parent': True
            }
        
        # Try each pattern
        for pattern, variant_name in self.VARIANT_PATTERNS:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                parent_name = name[:match.start()].strip()
                
                # CRITICAL CHECK: Make sure parent name still has model identifier
                if self.has_model_identifier(parent_name):
                    return {
                        'full_name': device_name,
                        'parent_name': parent_name,
                        'variant': variant_name,
                        'is_parent': False
                    }
        
        # No variant found - this is a parent model
        return {
            'full_name': device_name,
            'parent_name': device_name,
            'variant': None,
            'is_parent': True
        }
    
    def get_devices_by_brand(self, brand_name=None):
        """Get all devices for a specific brand"""
        if brand_name:
            self.cur.execute("""
                SELECT d.id, d.name, d.brand_id, b.name as brand_name
                FROM devices d
                JOIN brands b ON d.brand_id = b.id
                WHERE LOWER(b.name) = LOWER(%s)
                ORDER BY d.name
            """, (brand_name,))
        else:
            self.cur.execute("""
                SELECT d.id, d.name, d.brand_id, b.name as brand_name
                FROM devices d
                JOIN brands b ON d.brand_id = b.id
                ORDER BY b.name, d.name
            """)
        
        return self.cur.fetchall()
    
    def reset_classification(self):
        """Reset all classification data to start fresh"""
        print("\n🔄 Resetting existing classification...")
        self.cur.execute("""
            UPDATE devices 
            SET parent_id = NULL,
                is_parent = TRUE,
                variant_suffix = NULL
        """)
        self.conn.commit()
        print("✓ Classification reset complete")
    
    def classify_and_link_devices(self, brand_name=None, preview_only=False, reset=False):
        """
        Classify devices and create parent-child relationships.
        """
        print(f"\n🚀 Starting parent-child classification...")
        if brand_name:
            print(f"   Brand filter: {brand_name}")
        
        if reset and not preview_only:
            self.reset_classification()
        
        # Get devices
        devices = self.get_devices_by_brand(brand_name)
        total = len(devices)
        
        if total == 0:
            print(f"✗ No devices found")
            return
        
        print(f"   Found {total} devices to classify\n")
        
        # Step 1: Classify all devices
        classified = {}
        parent_map = defaultdict(list)  # Maps parent_name -> list of device_ids
        
        for device_id, device_name, brand_id, brand in devices:
            classification = self.extract_variant(device_name)
            classification['device_id'] = device_id
            classification['brand'] = brand
            classified[device_id] = classification
            
            # Build parent map - store ALL devices with this parent name
            parent_name = classification['parent_name']
            parent_map[parent_name].append(device_id)
        
        # Step 2: Identify true parents (devices that exist with exact parent name)
        true_parents = {}
        for parent_name, device_ids in parent_map.items():
            # Find if any device has EXACT name match as parent
            for device_id in device_ids:
                if classified[device_id]['full_name'] == parent_name:
                    true_parents[parent_name] = device_id
                    break
        
        # Step 3: Group by parent
        families = defaultdict(list)
        
        for device_id, info in classified.items():
            parent_name = info['parent_name']
            families[parent_name].append(info)
        
        # Step 4: Display results
        print("="*100)
        print("PARENT-CHILD RELATIONSHIPS")
        print("="*100)
        
        parent_count = 0
        child_count = 0
        solo_count = 0
        
        for parent_name in sorted(families.keys()):
            members = families[parent_name]
            
            # Only show if there are variants (more than 1 device)
            if len(members) > 1:
                print(f"\n👨 PARENT: {parent_name}")
                print("   " + "-" * 95)
                
                parent_found = False
                children = []
                
                for member in sorted(members, key=lambda x: (not x['is_parent'], x['variant'] or '')):
                    if member['full_name'] == parent_name:  # Exact match
                        parent_count += 1
                        parent_found = True
                        print(f"   ✓ {member['full_name']} (ID: {member['device_id']})")
                    else:
                        children.append(member)
                
                if not parent_found:
                    print(f"   ⚠ No exact parent found in database")
                
                if children:
                    print(f"\n   👶 CHILDREN ({len(children)}):")
                    for child in children:
                        child_count += 1
                        print(f"      → {child['full_name']} [{child['variant']}] (ID: {child['device_id']})")
            else:
                # Single device with no variants
                solo_count += 1
        
        print("\n" + "="*100)
        print(f"📊 SUMMARY:")
        print(f"   Total devices: {total}")
        print(f"   Parents with children: {parent_count}")
        print(f"   Children: {child_count}")
        print(f"   Solo devices (no variants): {solo_count}")
        print("="*100)
        
        if preview_only:
            print("\n⚠ PREVIEW MODE - No database updates performed")
            return
        
        # Step 5: Update database with relationships
        print("\n💾 Creating parent-child relationships in database...")
        
        updated = 0
        linked = 0
        
        for device_id, info in classified.items():
            try:
                if info['full_name'] == info['parent_name']:
                    # This is a parent - check if it has children
                    has_children = len(families[info['parent_name']]) > 1
                    
                    self.cur.execute("""
                        UPDATE devices
                        SET parent_id = NULL,
                            is_parent = %s,
                            variant_suffix = NULL
                        WHERE id = %s
                    """, (has_children, device_id))
                    updated += 1
                else:
                    # This is a child - find and link to parent
                    parent_id = true_parents.get(info['parent_name'])
                    
                    if parent_id:
                        self.cur.execute("""
                            UPDATE devices
                            SET parent_id = %s,
                                is_parent = FALSE,
                                variant_suffix = %s
                            WHERE id = %s
                        """, (parent_id, info['variant'], device_id))
                        linked += 1
                        updated += 1
                    else:
                        # Parent doesn't exist - keep as standalone
                        self.cur.execute("""
                            UPDATE devices
                            SET parent_id = NULL,
                                is_parent = TRUE,
                                variant_suffix = NULL
                            WHERE id = %s
                        """, (device_id,))
                        updated += 1
                
                if updated % 100 == 0:
                    print(f"   Progress: {updated}/{total} devices updated...")
                    
            except Exception as e:
                print(f"\n✗ Error updating device {info['full_name']}: {e}")
        
        self.conn.commit()
        print(f"\n✓ Successfully updated {updated} devices")
        print(f"   - {linked} children linked to parents")
    
    def show_family_tree(self, brand_name=None, limit=50):
        """Display parent-child relationships in a tree format"""
        print("\n" + "="*100)
        print("DEVICE FAMILY TREE")
        print("="*100)
        
        if brand_name:
            query = """
                SELECT 
                    p.id as parent_id,
                    p.name as parent_name,
                    b.name as brand,
                    c.id as child_id,
                    c.name as child_name,
                    c.variant_suffix
                FROM devices p
                JOIN brands b ON p.brand_id = b.id
                LEFT JOIN devices c ON p.id = c.parent_id
                WHERE p.is_parent = TRUE 
                AND EXISTS (SELECT 1 FROM devices WHERE parent_id = p.id)
                AND LOWER(b.name) = LOWER(%s)
                ORDER BY p.name, c.variant_suffix
                LIMIT %s
            """
            self.cur.execute(query, (brand_name, limit * 10))
        else:
            query = """
                SELECT 
                    p.id as parent_id,
                    p.name as parent_name,
                    b.name as brand,
                    c.id as child_id,
                    c.name as child_name,
                    c.variant_suffix
                FROM devices p
                JOIN brands b ON p.brand_id = b.id
                LEFT JOIN devices c ON p.id = c.parent_id
                WHERE p.is_parent = TRUE
                AND EXISTS (SELECT 1 FROM devices WHERE parent_id = p.id)
                ORDER BY b.name, p.name, c.variant_suffix
                LIMIT %s
            """
            self.cur.execute(query, (limit * 10,))
        
        results = self.cur.fetchall()
        
        current_parent = None
        family_num = 0
        
        for row in results:
            parent_id, parent_name, brand, child_id, child_name, variant = row
            
            if parent_id != current_parent:
                current_parent = parent_id
                family_num += 1
                
                if family_num > limit:
                    print(f"\n... (showing first {limit} families only)")
                    break
                
                print(f"\n{family_num}. {brand} - {parent_name} (ID: {parent_id})")
            
            if child_id:
                print(f"       ├── {child_name} [{variant}] (ID: {child_id})")
        
        print("\n" + "="*100)
    
    def close(self):
        """Close database connection"""
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
        print("\n✓ Database connection closed")


def main():
    """Main execution function"""
    classifier = ParentChildClassifier()
    
    try:
        classifier.connect_db()
        classifier.setup_parent_child_structure()
        
        print("\n" + "="*100)
        print("PARENT-CHILD DEVICE CLASSIFIER (STRICT MATCHING)")
        print("="*100)
        print("\nOptions:")
        print("1. Classify specific brand (e.g., Samsung)")
        print("2. Classify all brands")
        print("3. Preview classification (no database changes)")
        print("4. Show family tree")
        print("5. Reset all classifications and re-classify")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == '1':
            brand_name = input("Enter brand name (e.g., Samsung): ").strip()
            classifier.classify_and_link_devices(brand_name=brand_name, reset=True)
            
            show_tree = input("\nShow family tree? (y/n): ").strip().lower()
            if show_tree == 'y':
                classifier.show_family_tree(brand_name=brand_name)
        
        elif choice == '2':
            confirm = input("This will classify ALL brands. Continue? (y/n): ").strip().lower()
            if confirm == 'y':
                classifier.classify_and_link_devices(reset=True)
                
                show_tree = input("\nShow family tree? (y/n): ").strip().lower()
                if show_tree == 'y':
                    classifier.show_family_tree()
        
        elif choice == '3':
            brand_name = input("Enter brand name (or press Enter for all): ").strip()
            brand_name = brand_name if brand_name else None
            classifier.classify_and_link_devices(brand_name=brand_name, preview_only=True)
        
        elif choice == '4':
            brand_name = input("Enter brand name (or press Enter for all): ").strip()
            brand_name = brand_name if brand_name else None
            classifier.show_family_tree(brand_name=brand_name)
        
        elif choice == '5':
            confirm = input("This will RESET all existing classifications. Continue? (y/n): ").strip().lower()
            if confirm == 'y':
                brand_name = input("Enter brand name (or press Enter for all): ").strip()
                brand_name = brand_name if brand_name else None
                classifier.classify_and_link_devices(brand_name=brand_name, reset=True)
        
        else:
            print("Invalid choice")
        
        print("\n✅ Done!")
        
    except KeyboardInterrupt:
        print("\n\n⚠ Operation cancelled by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        classifier.close()


if __name__ == "__main__":
    main()