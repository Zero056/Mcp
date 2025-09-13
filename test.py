import asyncio
import json
import os
import sys
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

async def create_item_final():
    
    # print("🧪 Final Item Creation Test")
    # print("=" * 50)
    # 
    # Use the updated config with all required fields
    config_path = "config/multi_doctype_config.json"
    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        return
    
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        
        from src.erpnext_client import ERPNextClient
        from src.permissions import PermissionManager
        
        # Initialize clients
        erp_config = config["erpnext"]
        client = ERPNextClient(
            url=erp_config["url"],
            api_key=erp_config["api_key"],
            api_secret=erp_config["api_secret"]
        )
        
        perm_manager = PermissionManager(config)
        
        # Test connection
        print("\n Testing connection...")
        connected = await client.test_connection()
        print(f"Connected: {connected}")
        
        # Create test Item with comprehensive data
        print("\n* Creating test Item with comprehensive data...")
        try:
            timestamp = int(asyncio.get_event_loop().time())
            test_data = {
                "item_code": f"Api Item",
                "item_name": "Api Item",
                "is_stock_item": 1,
                "stock_uom": f"Nos",
                "item_group": f"All Item Groups",
            }
            
            print(f"   item_code: {test_data['item_code']}")
            print(f"   Item Type: {test_data['item_group']}")
            print(f"   stock uom: {test_data['stock_uom']}")
            
            # Filter to only allowed fields
            filtered_data = perm_manager.filter_allowed_fields(test_data, "Item")
            print(f"   Using {len(filtered_data)} fields: {list(filtered_data.keys())}")
            
            # Create the item_code
            print("   Creating item_code...")
            result = await client.create_item(filtered_data)
            
            if result and "data" in result:
                item_code = result["data"].get("item_code")
                print(f" *SUCCESS! Item created: {item_code}")
                
                # Quick verification
                try:
                    item_details = await client.get_item(item_code)
                    if item_details and "data" in item_details:
                        print(f"Verification passed: {item_details['data'].get('item_code')}")
                except:
                    print("Created but verification failed")
                    
            else:
                print(" Failed to create item_code")
                if result:
                    print(f"   Response: {json.dumps(result, indent=2)}")
                
        except Exception as e:
            print(f"Error: {e}")
            
            # Try with even more basic data if comprehensive fails
            print("\n*Trying with basic data only...")
            try:
                basic_data = {
                    "item_code": f"Basic Test {timestamp}",
                    "item_group": "All Item Groups"
                }
                
                basic_filtered = perm_manager.filter_allowed_fields(basic_data, "Item")
                print(f"   Trying with: {list(basic_filtered.keys())}")
                
                result = await client.create_item(basic_filtered)
                if result and "data" in result:
                    print(f"Basic creation worked: {result['data'].get('name')}")
                else:
                    print("Basic creation also failed")
                    
            except Exception as e2:
                print(f"Basic creation error: {e2}")
        
        # print("\n" + "=" * 50)
        print("✅ TEST COMPLETED!")
        
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(create_item_final())