# Dependencies for ha_creality_ws Integration

This document outlines all dependencies for the ha_creality_ws Home Assistant integration.

## Core Dependencies

### Python Packages (Auto-installed)
- `websockets>=10.4` - For WebSocket communication with Creality printers

### Home Assistant Core Dependencies
- `lovelace` - For Lovelace card support
- `http` - For HTTP client operations
- `frontend` - For frontend integration
- `persistent_notification` - For notification support

## Camera Dependencies

### K1 Family Printers (MJPEG)
- **No additional dependencies required**
- Direct MJPEG streaming from printer to Home Assistant
- Works with all standard Home Assistant camera cards

### K2 Family Printers (WebRTC)
- **go2rtc** (built-in Home Assistant service) - **Required**
  - Included with Home Assistant core (no HACS installation needed)
  - Automatically available on `localhost:11984`
  - Provides native WebRTC streaming support
  - Version requirement: 1.9.9+ (for native Creality WebRTC support)

## Installation Notes

### go2rtc Service
- **Included with Home Assistant**: No additional installation required
- **Automatic startup**: Starts automatically with Home Assistant
- **Port**: Available on `localhost:11984`
- **API endpoint**: `http://localhost:11984/api/streams` for stream management

### Verification
To verify go2rtc is running:
1. Open `http://localhost:11984` in your browser
2. Check `http://localhost:11984/api/streams` for configured streams
3. Look for go2rtc logs in Home Assistant logs

## Troubleshooting

### WebRTC Camera Issues
If K2 family cameras show fallback images instead of live video:

1. **Verify go2rtc is running**:
   ```bash
   curl http://localhost:11984/api/streams
   ```

2. **Check go2rtc version**:
   - Ensure Home Assistant version includes go2rtc 1.9.9+
   - Check Home Assistant logs for go2rtc startup messages

3. **Verify stream configuration**:
   - Check `http://localhost:11984/api/streams` for your printer's stream
   - Look for stream name: `creality_k2_[printer_ip]`

4. **Check WebRTC negotiation**:
   - Monitor Home Assistant logs for WebRTC offer/answer messages
   - Verify printer WebRTC signaling endpoint is accessible

### MJPEG Camera Issues
If K1 family cameras don't work:

1. **Verify printer MJPEG endpoint**:
   - Check `http://[printer_ip]:8080/?action=stream`
   - Ensure printer is powered on and accessible

2. **Check network connectivity**:
   - Verify printer is reachable from Home Assistant
   - Check firewall settings

## Version Compatibility

- **Home Assistant**: 2024.1.0+
- **go2rtc**: 1.9.9+ (for native Creality WebRTC support)
- **Python**: 3.11+

## No HACS Dependencies

This integration does **not** require any HACS integrations:
- ✅ Uses Home Assistant's built-in go2rtc service
- ✅ No additional camera cards needed
- ✅ Works with standard Home Assistant camera entities
- ✅ Native WebRTC support without external dependencies
