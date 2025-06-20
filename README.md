# Git Hosts Inventory Plugin

A custom Ansible inventory plugin that reads `hosts_*` files from a local directory (updated by cron from a Git repository) and builds dynamic inventory with DNS resolution and environment detection.

## Features

- **Local Directory Reading**: Reads from a local directory updated by cron job
- **DNS Resolution**: Performs CNAME lookups and adds DNS names to host variables
- **Environment Detection**: Automatically detects environments (PRD, ACC, QAS, TST) from group names
- **INI File Support**: Processes standard INI-format host files
- **Dynamic Grouping**: Creates groups based on environments, services, and custom rules
- **Caching**: Supports inventory caching for improved performance
- **Flexible Configuration**: YAML-based configuration with extensive customization options

## Installation

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up Directory Structure**:
   ```
   ansible-project/
   ├── inventory_plugins/
   │   └── git_hosts.py
   ├── inventory.yml
   ├── ansible.cfg
   └── requirements.txt
   ```

3. **Configure Ansible**: The `ansible.cfg` file should include:
   ```ini
   [defaults]
   inventory_plugins = ./inventory_plugins
   enable_plugins = git_hosts
   ```

## Configuration

### Basic Configuration (`inventory.yml`)

```yaml
plugin: git_hosts
hosts_directory: /var/lib/ansible/inventory
dns_resolution: true
environment_detection: true
```

### Advanced Configuration

```yaml
plugin: git_hosts
hosts_directory: /var/lib/ansible/inventory
dns_resolution: true
environment_detection: true
check_interval: 0  # File change checking disabled

# Caching
cache: true
cache_plugin: memory
cache_timeout: 3600

# Dynamic group creation
keyed_groups:
  - key: environment | lower
    prefix: env
    separator: "_"

# Custom variables
compose:
  ansible_host: ansible_host | default(inventory_hostname)
  short_name: inventory_hostname.split('.')[0]
  env: environment | lower if environment is defined else 'unknown'

# Conditional groups
groups:
  production: environment == "PRD"
  staging: environment == "TST"
  web_servers: "'web' in group_names"
```

## Directory Structure

Your local directory (updated by cron) should be organized by environment with hosts files in each:

```
/var/lib/ansible/inventory/
├── group_vars/
│   ├── all.yml
│   ├── prod.yml
│   ├── acc.yml
│   ├── tst.yml
│   └── qas.yml
├── host_vars/
├── prod/
│   ├── hosts.yml
│   ├── hosts.ini
│   └── hosts_web
├── acc/
│   ├── hosts.yml
│   └── hosts_db
├── tst/
│   ├── hosts.yml
│   ├── hosts_app
│   └── hosts_web
└── qas/
    ├── hosts.yml
    └── hosts_db
```

**Key Features:**
- **Environment Directories**: Each environment (prod, acc, tst, qas) has its own directory
- **Multiple Files**: Each environment can contain multiple hosts files
- **Flexible Naming**: Supports `hosts.yml`, `hosts.ini`, and `hosts_*` patterns
- **Auto Environment Detection**: Environment is detected from directory name

## Cron Setup

Use the provided script to update the directory from your Git repository:

1. Copy `update_inventory.sh` to `/usr/local/bin/`
2. Make it executable: `chmod +x /usr/local/bin/update_inventory.sh`
3. Configure environment variables or edit the script
4. Add to crontab:

```bash
# Update inventory every 5 minutes
*/5 * * * * /usr/local/bin/update_inventory.sh >/dev/null 2>&1

# Or with custom configuration
*/5 * * * * REPO_URL="https://github.com/company/inventory.git" LOCAL_DIR="/var/lib/ansible/inventory" /usr/local/bin/update_inventory.sh
```

### Host File Format

Each environment directory can contain multiple hosts files in INI format:

```ini
# prod/hosts.yml (or hosts.ini)
[web_servers]
web01.example.com ansible_user=webuser
web02.example.com ansible_user=webuser

[load_balancers]
lb01.example.com ansible_user=lbuser port=8080
lb02.example.com ansible_user=lbuser port=8080
```

```ini
# prod/hosts_database
[db_servers]
db01.example.com ansible_user=dbuser
db02.example.com ansible_user=dbuser

[redis_servers]
redis01.example.com ansible_user=redisuser
```

## Generated Inventory Structure

The plugin will create the following inventory structure:

### Groups
- **Original groups**: From the hosts files (e.g., `web_servers`, `db_servers`)
- **Environment groups**: `env_prd`, `env_acc`, `env_qas`, `env_tst`
- **Conditional groups**: `production`, `staging`, `web_servers`, etc.

### Host Variables
- **environment**: Automatically set from directory name (`PRD`, `ACC`, `QAS`, `TST`, etc.)
- **DNSName**: CNAME record if DNS resolution is enabled
- **Custom variables**: From host file definitions and compose rules

### Environment Detection
Environment is primarily detected from the directory name:
- `prod/` → `PRD`
- `acc/` → `ACC` 
- `tst/` → `TST`
- `qas/` → `QAS`
- Custom mappings supported (dev, staging, etc.)

## Usage Examples

### List All Hosts
```bash
ansible-inventory --list
```

### List Specific Group
```bash
ansible-inventory --list --group production
```

### View Host Variables
```bash
ansible-inventory --host web01.example.com
```

### Test Connectivity
```bash
ansible all -m ping
```

### Run Playbook on Environment
```bash
ansible-playbook site.yml --limit env_prd
```

## Environment Detection Rules

The plugin automatically detects environments based on directory names:

| Directory Name | Environment Code | Aliases |
|----------------|------------------|---------|
| `prod/` | PRD | `production/`, `prd/` |
| `acc/` | ACC | `acceptance/` |
| `tst/` | TST | `test/`, `testing/` |
| `qas/` | QAS | `quality/`, `qa/` |
| `dev/` | DEV | `development/` |
| `staging/` | STG | `stg/` |
| Other | Directory name (uppercase) | Custom directories |

**Fallback**: If no directory-based environment is detected, the plugin falls back to group name patterns (`*_PRD*`, `*_ACC*`, etc.)

## DNS Resolution

When `dns_resolution: true`, the plugin performs CNAME lookups for each host and adds the resolved name as `DNSName` variable.

**Example**:
```yaml
# Host: web01.internal.example.com
# CNAME: web01.external.example.com
hostvars:
  web01.internal.example.com:
    DNSName: web01.external.example.com
    environment: PRD
```

## Troubleshooting

### Common Issues

1. **Directory not found**:
   - Verify the hosts_directory path exists
   - Check directory permissions
   - Ensure cron job is running and updating the directory

2. **DNS resolution errors**:
   - Install `dnspython`: `pip install dnspython`
   - Check DNS server configuration
   - Disable DNS resolution if not needed: `dns_resolution: false`

3. **No hosts found**:
   - Verify environment directories (`prod/`, `acc/`, etc.) exist
   - Check that hosts files exist in environment directories
   - Verify `hosts_file_patterns` match your file naming
   - Review file permissions and format

### Debug Mode

Enable verbose output for debugging:
```bash
ansible-inventory --list -vvv
```

### Testing the Plugin

Create a test configuration:
```yaml
# test-inventory.yml
plugin: git_hosts
hosts_directory: ./test_hosts
dns_resolution: false
environment_detection: true
```

Test with:
```bash
ansible-inventory -i test-inventory.yml --list
```

## Security Considerations

- **Repository Access**: Ensure proper access controls on the inventory repository
- **Credentials**: Use SSH keys or tokens for private repositories
- **Sensitive Data**: Avoid storing sensitive information in host files
- **Network Access**: The plugin requires network access for git operations and DNS resolution

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This inventory plugin is provided as-is for educational and production use. 