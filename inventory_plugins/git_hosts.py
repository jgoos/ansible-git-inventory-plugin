#!/usr/bin/env python3

"""
Git Hosts Inventory Plugin for Ansible
Reads hosts_* files from a local directory (updated by cron) and builds dynamic inventory
with DNS resolution and environment detection.
"""

import json
import os
import glob
import sys
from ansible.plugins.inventory import BaseInventoryPlugin, Constructable, Cacheable
from ansible.errors import AnsibleError, AnsibleParserError
from ansible.module_utils._text import to_text
from ansible.utils.display import Display

try:
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

display = Display()

DOCUMENTATION = r'''
    name: git_hosts
    plugin_type: inventory
    short_description: Local directory based inventory plugin (git updated via cron)
    description:
        - Reads hosts_* files from a local directory
        - Directory is updated by external cron job from git repository
        - Builds Ansible inventory with DNS resolution
        - Automatically detects environments from group names
        - Supports INI format host files
    options:
        plugin:
            description: Token that ensures this is a source file for the 'git_hosts' plugin.
            required: True
            choices: ['git_hosts']
        hosts_directory:
            description: Local directory containing environment subdirectories with hosts files (updated by cron)
            required: True
            type: str
        environment_dirs:
            description: List of environment directory names to scan
            required: False
            default: ['prod', 'acc', 'tst', 'qas']
            type: list
        hosts_file_patterns:
            description: File patterns to match for hosts files in each environment directory
            required: False
            default: ['hosts.yml', 'hosts.ini', 'hosts_*']
            type: list
        environment_mapping:
            description: Custom mapping of directory names to environment codes
            required: False
            default: {}
            type: dict
        auto_environment_patterns:
            description: Enable automatic environment code generation patterns
            required: False
            default: True
            type: bool
        dns_resolution:
            description: Enable DNS CNAME resolution for host names
            required: False
            default: True
            type: bool
        environment_detection:
            description: Enable automatic environment detection from group names
            required: False
            default: True
            type: bool
        check_interval:
            description: How often to check for file changes (in seconds, 0 to disable)
            required: False
            default: 0
            type: int
        keyed_groups:
            description: List of keyed groups to create
            type: list
            default: []
        compose:
            description: List of custom variables to compose
            type: dict
            default: {}
        groups:
            description: List of groups to create
            type: dict
            default: {}
    extends_documentation_fragment:
        - constructed
        - inventory_cache
'''

EXAMPLES = r'''
# Example inventory configuration file (inventory.yml)
plugin: git_hosts
hosts_directory: /var/lib/ansible/inventory
environment_dirs: ['prod', 'acc', 'tst', 'qas', 'dt', 'sandbox']
hosts_file_patterns: ['hosts.yml', 'hosts.ini', 'hosts_*']
dns_resolution: true
environment_detection: true
auto_environment_patterns: true
check_interval: 300  # Check for changes every 5 minutes

# Custom environment mappings (optional)
environment_mapping:
  sandbox: "SBOX"
  dt: "DT"
  integration: "INT"

# Create additional groups based on environment
keyed_groups:
  - key: environment | lower
    prefix: env
    separator: "_"

# Compose additional variables
compose:
  ansible_host: ansible_host | default(inventory_hostname)
  short_name: inventory_hostname.split('.')[0]

# Create groups based on conditions
groups:
  production: environment == "PRD"
  staging: environment == "TST"
  web_servers: "'web' in group_names"
'''


class InventoryModule(BaseInventoryPlugin, Constructable, Cacheable):
    NAME = 'git_hosts'

    def verify_file(self, path):
        """Return true/false if this is possibly a valid file for this plugin to consume"""
        valid = False
        if super(InventoryModule, self).verify_file(path):
            # Check if it's a YAML file and contains our plugin name
            if path.endswith(('.yaml', '.yml')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):
        """Parse the inventory file and return dynamic inventory"""
        super(InventoryModule, self).parse(inventory, loader, path, cache)

        # Read configuration
        self._read_config_data(path)
        
        # Get configuration options
        self.hosts_directory = self.get_option('hosts_directory')
        self.environment_dirs = self.get_option('environment_dirs')
        self.hosts_file_patterns = self.get_option('hosts_file_patterns')
        self.environment_mapping = self.get_option('environment_mapping')
        self.auto_environment_patterns = self.get_option('auto_environment_patterns')
        self.dns_resolution = self.get_option('dns_resolution')
        self.environment_detection = self.get_option('environment_detection')
        self.check_interval = self.get_option('check_interval')

        if not self.hosts_directory:
            raise AnsibleParserError("hosts_directory is required")

        if self.dns_resolution and not HAS_DNS:
            display.warning("DNS resolution requested but dnspython is not available. "
                          "Install with: pip install dnspython")
            self.dns_resolution = False

        # Validate directory exists and process files
        if not os.path.exists(self.hosts_directory):
            raise AnsibleError(f"Hosts directory does not exist: {self.hosts_directory}")
        
        if not os.path.isdir(self.hosts_directory):
            raise AnsibleError(f"Hosts directory path is not a directory: {self.hosts_directory}")

        try:
            self._process_environment_directories()
        except Exception as e:
            raise AnsibleError(f"Failed to process hosts directory: {to_text(e)}")



    def _process_environment_directories(self):
        """Process environment directories and their hosts files"""
        # Initialize inventory structure
        inventory_data = {
            "_meta": {"hostvars": {}},
            "all": {"children": ["ungrouped"]}
        }

        total_files = 0
        for env_dir in self.environment_dirs:
            # Security check: prevent path traversal
            if ".." in env_dir or os.path.isabs(env_dir):
                display.warning(f"Skipping potentially unsafe environment directory: {env_dir}")
                continue
            
            env_path = os.path.join(self.hosts_directory, env_dir)
            
            if not os.path.exists(env_path):
                display.vv(f"Environment directory does not exist: {env_path}")
                continue
                
            if not os.path.isdir(env_path):
                display.vv(f"Environment path is not a directory: {env_path}")
                continue

            display.v(f"Processing environment directory: {env_dir}")
            
            # Find all hosts files in this environment directory
            env_files = self._find_hosts_files(env_path)
            
            if not env_files:
                display.vv(f"No hosts files found in {env_path}")
                continue

            display.v(f"Found {len(env_files)} hosts files in {env_dir}: {[os.path.basename(f) for f in env_files]}")
            total_files += len(env_files)

            # Process each hosts file in this environment
            for filename in env_files:
                self._process_single_host_file(filename, inventory_data, env_dir)

        if total_files == 0:
            display.warning(f"No hosts files found in any environment directories")
            return

        display.v(f"Processed {total_files} total hosts files across environments")

        # Build Ansible inventory from processed data
        self._build_ansible_inventory(inventory_data)

    def _find_hosts_files(self, env_path):
        """Find all hosts files in an environment directory using configured patterns"""
        hosts_files = []
        
        for pattern in self.hosts_file_patterns:
            pattern_path = os.path.join(env_path, pattern)
            matched_files = glob.glob(pattern_path)
            hosts_files.extend(matched_files)
        
        # Remove duplicates and ensure files exist
        unique_files = []
        seen = set()
        for f in hosts_files:
            if f not in seen and os.path.isfile(f):
                unique_files.append(f)
                seen.add(f)
        
        return unique_files

    def _process_single_host_file(self, filename, inventory_data, environment=None):
        """Process a single hosts file"""
        display.vv(f"Processing file: {filename} (environment: {environment})")
        
        try:
            with open(filename, 'r') as f:
                entries = f.readlines()
        except IOError as e:
            display.warning(f"Could not read file {filename}: {e}")
            return

        group = "ungrouped"
        host = ""

        for entry in entries:
            entry = entry.strip()
            if not entry or entry.startswith('#'):
                continue

            # Check for group definition [groupname]
            if "[" in entry and "]" in entry:
                group = entry[entry.index("[")+1:entry.index("]")]
                if not group:  # Empty group name
                    display.warning(f"Empty group name in {filename}, skipping")
                    continue
                if group not in inventory_data["all"]["children"]:
                    inventory_data["all"]["children"].append(group)
                continue
            
            # Process host entries
            if entry and not entry.startswith("#"):
                entry_list = entry.split()
                
                for i, item in enumerate(entry_list):
                    if i == 0:
                        host = item
                        # Initialize group if not exists
                        if group not in inventory_data:
                            inventory_data[group] = {"hosts": []}
                        
                        # Add host to group if not already present
                        if host not in inventory_data[group]["hosts"]:
                            inventory_data[group]["hosts"].append(host)
                        
                        # Initialize host vars if not exists
                        if host not in inventory_data["_meta"]["hostvars"]:
                            inventory_data["_meta"]["hostvars"][host] = {}
                        else:
                            # Warn about duplicate host
                            display.warning(f"Host {host} found in multiple locations, variables may be overwritten")
                    else:
                        # Process host variables (key=value format)
                        if "=" in item:
                            item_key, item_value = item.split("=", 1)
                            inventory_data["_meta"]["hostvars"][host][item_key] = item_value

                # Set environment from directory name if provided and environment detection is enabled
                if host and environment and self.environment_detection:
                    self._set_environment_from_directory(host, environment, inventory_data)

                # DNS Resolution
                if host and self.dns_resolution:
                    self._resolve_dns(host, inventory_data)

                # Fallback environment detection from group name (if not set by directory)
                if host and group and self.environment_detection and environment is None:
                    self._detect_environment(host, group, inventory_data)

    def _resolve_dns(self, hostname, inventory_data):
        """Perform DNS CNAME resolution for hostname"""
        try:
            answer = dns.resolver.resolve(hostname, "CNAME")
            for cname_val in answer:
                inventory_data["_meta"]["hostvars"][hostname]["DNSName"] = cname_val.target.to_text()
                break
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            # These are expected for hosts without CNAME records
            pass
        except Exception as e:
            display.vv(f"DNS resolution failed for {hostname}: {e}")

    def _set_environment_from_directory(self, hostname, env_dir, inventory_data):
        """Set environment based on directory name with dynamic mapping"""
        if not hostname or not env_dir:
            return

        environment = self._generate_environment_code(env_dir)
        inventory_data["_meta"]["hostvars"][hostname]["environment"] = environment
        
        display.vv(f"Set environment {environment} for host {hostname} from directory {env_dir}")

    def _generate_environment_code(self, env_dir):
        """Generate environment code from directory name using multiple strategies"""
        if not env_dir:
            return "MISC"

        env_dir_lower = env_dir.lower()
        
        # 1. Check custom user mapping first
        if self.environment_mapping and env_dir_lower in self.environment_mapping:
            return self.environment_mapping[env_dir_lower]
        
        # 2. Check built-in common mappings (for backward compatibility)
        built_in_mapping = {
            'prod': 'PRD',
            'production': 'PRD',
            'prd': 'PRD',
            'acc': 'ACC',
            'acceptance': 'ACC',
            'tst': 'TST',
            'test': 'TST',
            'testing': 'TST',
            'qas': 'QAS',
            'quality': 'QAS',
            'qa': 'QAS',
            'dev': 'DEV',
            'development': 'DEV',
            'staging': 'STG',
            'stg': 'STG'
        }
        
        if env_dir_lower in built_in_mapping:
            return built_in_mapping[env_dir_lower]
        
        # 3. Apply automatic patterns if enabled
        if self.auto_environment_patterns:
            return self._auto_generate_environment_code(env_dir)
        
        # 4. Fallback to uppercase directory name
        return env_dir.upper()

    def _auto_generate_environment_code(self, env_dir):
        """Automatically generate environment codes using intelligent patterns"""
        env_dir_clean = env_dir.lower().strip()
        
        # Pattern 1: If 3 characters or less, use uppercase
        if len(env_dir_clean) <= 3:
            return env_dir_clean.upper()
        
        # Pattern 2: Look for common abbreviation patterns
        # Remove common suffixes (prioritize longer suffixes first)
        suffixes_to_remove = ['environment', 'ment', 'env']
        for suffix in suffixes_to_remove:
            if env_dir_clean.endswith(suffix):
                base = env_dir_clean[:-len(suffix)].rstrip('-_')
                if len(base) >= 2:
                    return base.upper()
        
        # Pattern 3: Generate abbreviation from longer names
        if len(env_dir_clean) > 3:
            # Try to create meaningful abbreviation
            
            # For hyphenated/underscored names, take first letter of each part
            if '-' in env_dir_clean or '_' in env_dir_clean:
                parts = env_dir_clean.replace('_', '-').split('-')
                if len(parts) > 1:
                    abbrev = ''.join([part[0] for part in parts if part and part[0].isalpha()])
                    if len(abbrev) >= 2:
                        return abbrev.upper()
            
            # For camelCase or mixed case, extract capitals
            if any(c.isupper() for c in env_dir):
                capitals = ''.join([c for c in env_dir if c.isupper()])
                if len(capitals) >= 2:
                    return capitals
            
            # For words with vowels, try consonant abbreviation
            vowels = 'aeiou'
            consonants = ''.join([c for c in env_dir_clean if c not in vowels and c.isalpha()])
            if len(consonants) >= 3:
                return consonants[:3].upper()
            elif len(consonants) == 2:
                return consonants.upper()
            
            # Take first 3 characters as last resort
            return env_dir_clean[:3].upper()
        
        # Final fallback
        return env_dir.upper()

    def _detect_environment(self, hostname, group, inventory_data):
        """Detect and set environment based on group name (fallback method)"""
        if not hostname or not group:
            return

        # Skip if environment already set by directory
        if "environment" in inventory_data["_meta"]["hostvars"][hostname]:
            return

        environment = "MISC"  # default
        
        if "_PRD" in group:
            environment = "PRD"
        elif "_ACC" in group:
            environment = "ACC"
        elif "_QAS" in group:
            environment = "QAS"
        elif "_TST" in group:
            environment = "TST"

        inventory_data["_meta"]["hostvars"][hostname]["environment"] = environment

    def _build_ansible_inventory(self, inventory_data):
        """Build Ansible inventory from processed data"""
        # Add all groups
        for group_name, group_data in inventory_data.items():
            if group_name == "_meta":
                continue
            
            if group_name == "all":
                # Handle special 'all' group
                for child in group_data.get("children", []):
                    if child != "ungrouped" or child in inventory_data:
                        self.inventory.add_group(child)
            else:
                # Add regular groups
                self.inventory.add_group(group_name)
                
                # Add hosts to groups
                for host in group_data.get("hosts", []):
                    self.inventory.add_host(host, group=group_name)

        # Add host variables
        for hostname, hostvars in inventory_data["_meta"]["hostvars"].items():
            for var_name, var_value in hostvars.items():
                self.inventory.set_variable(hostname, var_name, var_value)

        # Apply constructed features (keyed_groups, compose, groups)
        self._apply_constructed()

    def _apply_constructed(self):
        """Apply constructed inventory features"""
        # This method uses the Constructable mixin to apply
        # keyed_groups, compose, and groups configurations
        for host in self.inventory.hosts:
            hostvars = self.inventory.get_host(host).get_vars()
            
            # Apply composed variables
            self._set_composite_vars(
                self.get_option('compose'),
                hostvars,
                host
            )
            
            # Apply keyed groups
            self._add_host_to_keyed_groups(
                self.get_option('keyed_groups'),
                hostvars,
                host
            )
            
            # Apply conditional groups
            self._add_host_to_composed_groups(
                self.get_option('groups'),
                hostvars,
                host
            ) 