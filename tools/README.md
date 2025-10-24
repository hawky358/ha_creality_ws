# Development Tools

This directory contains tools for developing and deploying the Creality WebSocket integration.

## deploy_to_ha.sh

Deployment script that syncs code from the development repository to production Home Assistant.

### Usage

```bash
# Dry run - see what would happen
./tools/deploy_to_ha.sh

# Full deployment with backup and restart
./tools/deploy_to_ha.sh --run

# Deploy without creating backup
./tools/deploy_to_ha.sh --run --no-backup

# Deploy without restarting Home Assistant
./tools/deploy_to_ha.sh --run --no-restart

# Deploy only the Lovelace card (k_printer_card.js)
./tools/deploy_to_ha.sh --run --card

# Deploy only the card without backup or restart
./tools/deploy_to_ha.sh --run --card --no-backup --no-restart
```

### What it does

**Full deployment mode (default):**
1. **Creates timestamped backup** of production code in `/root/ha_creality_ws/backups/`
2. **Syncs code** from development repo to production Home Assistant
3. **Removes cache files** (`__pycache__`, `*.pyc`, `*.pyo`) from production
4. **Restarts Home Assistant** via API call

**Card-only mode (`--card`):**
1. **Creates backup** of only the `k_printer_card.js` file
2. **Syncs only the card file** from development to production
3. **Restarts Home Assistant** via API call (optional)

### Configuration

- **Repository**: `/root/ha_creality_ws` (development)
- **Production**: `/root/ha_config/custom_components/ha_creality_ws` (SMB mount)
- **Backups**: `/root/ha_creality_ws/backups/` (timestamped)
- **API**: Home Assistant restart via authenticated API call

### Safety Features

- **Dry-run by default**: Use `--run` to actually perform changes
- **Automatic backups**: Creates timestamped backups before changes
- **Validation**: Checks that source and destination directories exist
- **Error handling**: Stops on errors and provides clear messages
- **Cache cleanup**: Removes Python cache files to prevent issues

### Examples

```bash
# Quick development cycle
./tools/deploy_to_ha.sh --run

# Deploy without backup (faster, but no rollback)
./tools/deploy_to_ha.sh --run --no-backup

# Deploy without restart (manual restart later)
./tools/deploy_to_ha.sh --run --no-restart
```
