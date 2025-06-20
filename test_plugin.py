#!/usr/bin/env python3
"""
Test script for the git_hosts inventory plugin
This script helps validate the plugin installation and configuration.
"""

import os
import sys
import yaml
import json
import subprocess
from pathlib import Path

def check_requirements():
    """Check if required packages are installed"""
    print("🔍 Checking requirements...")
    
    try:
        import ansible
        print(f"✅ Ansible {ansible.__version__} installed")
    except ImportError:
        print("❌ Ansible not installed")
        return False
    
    try:
        import dns.resolver
        print("✅ dnspython installed")
    except ImportError:
        print("⚠️  dnspython not installed (DNS resolution will be disabled)")
    
    # Check git availability
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Git available: {result.stdout.strip()}")
        else:
            print("❌ Git not available")
            return False
    except FileNotFoundError:
        print("❌ Git not found in PATH")
        return False
    
    return True

def check_file_structure():
    """Check if the required files are present"""
    print("\n📁 Checking file structure...")
    
    required_files = {
        'inventory_plugins/git_hosts.py': 'Inventory plugin',
        'inventory.yml': 'Inventory configuration',
        'ansible.cfg': 'Ansible configuration',
        'requirements.txt': 'Python requirements'
    }
    
    all_present = True
    for file_path, description in required_files.items():
        if os.path.exists(file_path):
            print(f"✅ {description}: {file_path}")
        else:
            print(f"❌ Missing {description}: {file_path}")
            all_present = False
    
    return all_present

def validate_inventory_config():
    """Validate the inventory configuration file"""
    print("\n⚙️  Validating inventory configuration...")
    
    try:
        with open('inventory.yml', 'r') as f:
            config = yaml.safe_load(f)
        
        required_keys = ['plugin', 'repo_url']
        for key in required_keys:
            if key in config:
                print(f"✅ {key}: {config[key]}")
            else:
                print(f"❌ Missing required key: {key}")
                return False
        
        # Check optional but important keys
        optional_keys = ['repo_branch', 'repo_path', 'dns_resolution', 'environment_detection']
        for key in optional_keys:
            if key in config:
                print(f"ℹ️  {key}: {config[key]}")
        
        return True
        
    except FileNotFoundError:
        print("❌ inventory.yml not found")
        return False
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML in inventory.yml: {e}")
        return False

def test_inventory_plugin():
    """Test the inventory plugin functionality"""
    print("\n🧪 Testing inventory plugin...")
    
    # Create a minimal test configuration
    test_config = {
        'plugin': 'git_hosts',
        'hosts_directory': './test_hosts',  # Local test directory
        'dns_resolution': False,  # Disable for testing
        'environment_detection': True
    }
    
    test_config_file = 'test_inventory.yml'
    
    try:
        # Create test hosts directory with environment structure
        os.makedirs('./test_hosts', exist_ok=True)
        os.makedirs('./test_hosts/prod', exist_ok=True)
        os.makedirs('./test_hosts/tst', exist_ok=True)
        
        # Create sample hosts files for different environments
        with open('./test_hosts/prod/hosts.ini', 'w') as f:
            f.write("""# Production hosts file
[web_servers]
web01.prod.local ansible_user=webuser
web02.prod.local ansible_user=webuser

[db_servers]
db01.prod.local ansible_user=dbuser
""")
        
        with open('./test_hosts/tst/hosts.ini', 'w') as f:
            f.write("""# Test hosts file
[web_servers]
web01.test.local ansible_user=testuser
web02.test.local ansible_user=testuser

[app_servers]
app01.test.local ansible_user=appuser
""")
        
        # Write test configuration
        with open(test_config_file, 'w') as f:
            yaml.dump(test_config, f)
        
        print(f"📝 Created test configuration: {test_config_file}")
        print(f"📝 Created test hosts directory: ./test_hosts")
        
        # Test inventory list
        print("🔍 Testing ansible-inventory --list...")
        result = subprocess.run(
            ['ansible-inventory', '-i', test_config_file, '--list'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            try:
                inventory_data = json.loads(result.stdout)
                print("✅ Inventory plugin executed successfully")
                print(f"📊 Found {len(inventory_data.get('_meta', {}).get('hostvars', {}))} hosts")
                
                # Show some sample data
                if inventory_data.get('_meta', {}).get('hostvars'):
                    print("🏠 Sample hosts:")
                    for i, host in enumerate(list(inventory_data['_meta']['hostvars'].keys())[:3]):
                        print(f"   - {host}")
                        if i >= 2:  # Show max 3 hosts
                            break
                
            except json.JSONDecodeError:
                print(f"⚠️  Plugin executed but output is not valid JSON")
                print(f"Output: {result.stdout[:200]}...")
        else:
            print(f"❌ Inventory plugin failed: {result.stderr}")
            return False
        
        return True
        
    except subprocess.TimeoutExpired:
        print("❌ Inventory test timed out")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    finally:
        # Clean up test files
        if os.path.exists(test_config_file):
            os.remove(test_config_file)
        import shutil
        if os.path.exists('./test_hosts'):
            shutil.rmtree('./test_hosts')

def main():
    """Main test function"""
    print("🚀 Git Hosts Inventory Plugin Test Suite")
    print("=" * 50)
    
    tests = [
        ("Requirements Check", check_requirements),
        ("File Structure Check", check_file_structure),
        ("Configuration Validation", validate_inventory_config),
        ("Plugin Functionality Test", test_inventory_plugin)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}")
        print("-" * len(test_name))
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n📋 Test Summary")
    print("=" * 20)
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("\n🎉 All tests passed! Your inventory plugin is ready to use.")
        print("\nNext steps:")
        print("1. Update inventory.yml with your actual repository URL")
        print("2. Test with: ansible-inventory --list")
        print("3. Run your playbooks: ansible-playbook site.yml")
    else:
        print("\n⚠️  Some tests failed. Please address the issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 