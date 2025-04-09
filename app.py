from flask import Flask, request, Response
import requests
import time
import wakeonlan
import os
import yaml
import logging
import sys
from urllib.parse import urljoin
from waitress import serve

__version__ = "0.1.0"

# Set up logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
SERVICES_CONFIG_PATH = os.getenv('SERVICES_CONFIG_PATH', '/config/services.yaml')
GLOBAL_POLL_INTERVAL = int(os.getenv('GLOBAL_POLL_INTERVAL', 5))  # seconds
GLOBAL_MAX_RETRIES = int(os.getenv('GLOBAL_MAX_RETRIES', 10))
SERVER_PORT = int(os.getenv('SERVER_PORT', 3000))
GLOBAL_REQUEST_TIMEOUT = int(os.getenv('GLOBAL_REQUEST_TIMEOUT', 5))  # seconds
GLOBAL_AWAKE_REQUEST_TIMEOUT = int(os.getenv('GLOBAL_AWAKE_REQUEST_TIMEOUT', GLOBAL_REQUEST_TIMEOUT))  # seconds

def get_service_configs():

    service_configs = {}
    logger.debug(f"Loading service configurations from {SERVICES_CONFIG_PATH} and environment variables")

    # Load from YAML file if it exists
    yaml_file_path = SERVICES_CONFIG_PATH
    if os.path.exists(yaml_file_path):
        logger.debug(f"Found YAML config file at {yaml_file_path}")
        with open(yaml_file_path, 'r') as file:
            yaml_config = yaml.safe_load(file)
            logger.debug(f"Loaded YAML config: {yaml_config}")
            for host, config in yaml_config.items():
                host = host.lower()
                service_configs[host] = {
                    "base_url": config.get("base_url"),
                    "awake_check_endpoint": config.get("awake_check_endpoint"),
                    "mac_address": config.get("mac_address"),
                    "poll_interval": int(config.get("poll_interval", GLOBAL_POLL_INTERVAL)),
                    "max_retries": int(config.get("max_retries", GLOBAL_MAX_RETRIES)),
                    "request_timeout": int(config.get("request_timeout", GLOBAL_REQUEST_TIMEOUT)),
                    "awake_request_timeout": int(config.get("awake_request_timeout", GLOBAL_AWAKE_REQUEST_TIMEOUT)),
                }
                logger.debug(f"Added service from YAML: {host} with config: {service_configs[host]}")
    else:
        logger.warning(f"YAML config file not found at {yaml_file_path}")

    # Process environment variables to override or add service configurations
    env_override_count = 0

    PREFIX = 'SERVICE_'
    VALID_ENV_SUFFIXES = {
        "BASE_URL",
        "AWAKE_CHECK_ENDPOINT",
        "MAC_ADDRESS",
        "POLL_INTERVAL",
        "MAX_RETRIES",
        "REQUEST_TIMEOUT",
        "AWAKE_REQUEST_TIMEOUT",
    }
    SUFFIX_TO_CONFIG_KEY = {s: s.lower() for s in VALID_ENV_SUFFIXES}
    NUMERIC_CONFIG_KEYS = {
        "poll_interval",
        "max_retries",
        "request_timeout",
        "awake_request_timeout",
    }
    DEFAULT_CONFIG_TEMPLATE = {
        "base_url": None,
        "awake_check_endpoint": None,
        "mac_address": None,
        "poll_interval": GLOBAL_POLL_INTERVAL,
        "max_retries": GLOBAL_MAX_RETRIES,
        "request_timeout": GLOBAL_REQUEST_TIMEOUT,
        "awake_request_timeout": GLOBAL_AWAKE_REQUEST_TIMEOUT,
    }

    env_override_count = 0


    logger.info("Scanning environment variables for service configurations...")

    VALID_SUFFIX_MAP = {'_' + s: s for s in VALID_ENV_SUFFIXES}

    for key, value in os.environ.items():
        if not key.startswith(PREFIX):
            continue # Skip variables not starting with the prefix

        matched_env_suffix = None
        extracted_host = None

        for suffix_with_underscore, original_suffix in VALID_SUFFIX_MAP.items():
            if key.endswith(suffix_with_underscore):
                # Check if this is the longest match. If suffixes overlap, this is needed to make sure this is the longest match.
                # For current valid suffixes, it doesn't matter, but we'll do this in case overlapping keys are added.
                if matched_env_suffix is None or len(original_suffix) > len(matched_env_suffix):
                    matched_env_suffix = original_suffix

        if matched_env_suffix:
            suffix_with_underscore = '_' + matched_env_suffix
            end_of_host_pos = len(key) - len(suffix_with_underscore)
            host_part = key[len(PREFIX):end_of_host_pos]

            if not host_part:
                logger.warning(f"Ignoring env var '{key}': Contains prefix and valid suffix but no host.")
                continue

            host = host_part.lower()
            config_key = SUFFIX_TO_CONFIG_KEY[matched_env_suffix]

            host_config = service_configs.setdefault(host, DEFAULT_CONFIG_TEMPLATE.copy())

            try:
                if config_key in NUMERIC_CONFIG_KEYS:
                    host_config[config_key] = int(value)
                else:
                    host_config[config_key] = value

                logger.debug(f"Applied config: host='{host}', key='{config_key}', value='{host_config[config_key]}' (from env var '{key}')")
                env_override_count += 1

            except (ValueError, TypeError) as e:
                logger.error(f"Failed to apply config from env var '{key}={value}' for host '{host}', key '{config_key}': Invalid value format - {e}")

        else:
            logger.debug(f"Ignoring env var '{key}': Does not end with a known service suffix.")


    logger.info(f"Finished scanning environment variables. Applied {env_override_count} overrides.")
        
    # Validate all services have required configuration
    valid_services = {}
    for host, config in service_configs.items():
        if not (config["base_url"] and config["awake_check_endpoint"] and config["mac_address"]):
            logger.error(f"Service {host} does not have all of the required config values: base URL, awake check endpoint, and MAC address")
            continue
        valid_services[host] = config
    
    if env_override_count > 0:
        logger.debug(f"Applied {env_override_count} configuration overrides from environment variables")
    else:
        logger.debug("No service configurations found in environment variables")

    logger.info(f"Loaded {len(valid_services)} total valid services: {list(valid_services.keys())}")
    return valid_services

service_configs = get_service_configs()

def send_wol_packet(mac_address):
    logger.info(f"Sending WoL packet to {mac_address}")
    wakeonlan.send_magic_packet(mac_address)

def is_server_awake(url, timeout):
    try:
        # Simple GET request for awake check. Connection pooling handles cleanup.
        response = requests.request(
            method='GET',
            url=url,
            timeout=timeout
        )
        logger.debug(f"Awake check to {url} status: {response.status_code}")
        if 200 <= response.status_code < 300:
             logger.info(f"Server at {url} is awake (status: {response.status_code})")
             return True
        else:
             logger.info(f"Server at {url} responded status {response.status_code}. Considering not awake.")
             return False
    except requests.RequestException as e:
        logger.info(f"Awake check to {url} failed: {e}")
        return False

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def proxy_request(path):
    original_request = request
    data = original_request.data
    headers = {key: value for (key, value) in original_request.headers if key != 'Host'}
    
    logger.debug(f"Received request for path: {path}, method: {original_request.method}")
    logger.debug(f"Request headers: {original_request.headers}")

    host_header = original_request.headers.get('Host')
    if not host_header:
        logger.error("Host header is missing.")
        return "Host header is missing.", 400
    
    logger.debug(f"Processing request with Host header: {host_header}")
    logger.debug(f"Available services: {list(service_configs.keys())}")

    # Check if the host matches any of the configured services
    target_service = None
    for identifier in service_configs:
        logger.debug(f"Comparing host header '{host_header}' with service identifier '{identifier}'")
        if host_header == identifier:
            target_service = identifier
            logger.debug(f"Found matching service: {target_service}")
            break

    if not target_service:
        logger.error(f"Unknown target service: {host_header}. Available services: {list(service_configs.keys())}")
        return f"Unknown target service: {host_header}.", 404

    config = service_configs.get(target_service)
    if not config:
        logger.error(f"Unknown target service: {target_service}. This should not happen as we already checked the service exists.")
        return f"Unknown target service: {target_service}.", 404
    
    logger.debug(f"Using configuration for service {target_service}: {config}")
    base_url = config["base_url"]
    destination_url = urljoin(base_url, request.full_path)
    awake_check_endpoint = config["awake_check_endpoint"]
    awake_check_url = urljoin(base_url, awake_check_endpoint)
    mac_address = config["mac_address"]
    poll_interval = config["poll_interval"]
    max_retries = config["max_retries"]
    request_timeout = config["request_timeout"]
    awake_request_timeout = config["awake_request_timeout"]
    
    # Poll until the server is awake
    retries = -1  # First try is not a retry, so start from -1
    server_awake = False
    
    while retries < max_retries:
        if retries > -1:
            logger.info(f"Server {target_service} is not awake. Sending wake-on-LAN magic packet and retrying in {poll_interval} seconds...")
            send_wol_packet(mac_address)
            time.sleep(poll_interval)

        server_awake = is_server_awake(awake_check_url, awake_request_timeout)
        
        if server_awake:
            break

        retries += 1

    if not server_awake:
        logger.error(f"Failed to reach the server {target_service} after {max_retries} attempts.")
        return f"Failed to reach the server {target_service} after {max_retries} attempts.", 503
    
    # Make the actual request
    try:
        response = requests.request(
            method=original_request.method,
            url=destination_url,
            data=data,
            headers=headers,
            timeout=request_timeout, # Timeout for connection/initial read; should not time out in middle of stream
            stream=True # Always use stream=True to handle both streaming and non-streaming responses robustly
        )
        logger.info(f"Proxying response from {destination_url} with status code: {response.status_code}")

        # Filter out hop-by-hop headers that shouldn't be forwarded directly.
        # Let Flask/Waitress handle Content-Length or Transfer-Encoding as needed.
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(name, value) for (name, value) in response.headers.items()
                            if name.lower() not in excluded_headers]

        # Create a streaming Flask response using iter_content.
        # This works correctly whether the original response from the downstream server
        # was chunked (streaming) or had a fixed Content-Length (non-streaming).
        return Response(response.iter_content(chunk_size=8192), status=response.status_code, headers=response_headers)
    except requests.RequestException as e:
        logger.error(f"Request failed after server {target_service} woke up: {e}")
        return f"Failed to reach the server {target_service} after it woke up.", 503

if __name__ == '__main__':
    logger.info(f"Starting wake-on-http server on port {SERVER_PORT}")
    logger.info(f"Log level set to: {LOG_LEVEL}")
    logger.info(f"Services config path: {SERVICES_CONFIG_PATH}")
    logger.info(f"Global poll interval: {GLOBAL_POLL_INTERVAL} seconds")
    logger.info(f"Global max retries: {GLOBAL_MAX_RETRIES}")
    logger.info(f"Global request timeout: {GLOBAL_REQUEST_TIMEOUT} seconds")
    logger.info(f"Global awake request timeout: {GLOBAL_AWAKE_REQUEST_TIMEOUT} seconds")
    
    if not service_configs:
        logger.error("No services configured! Please provide configuration via services.yaml or environment variables. Exiting.")
        sys.exit(1) # Exit if no services are configured
    else:
        logger.info(f"Configured services:")
        for service_name, config in service_configs.items():
            logger.info(f"  - {service_name}:")
            logger.info(f"    Base URL: {config['base_url']}")
            logger.info(f"    Awake Check Endpoint: {config['awake_check_endpoint']}")
            logger.info(f"    MAC Address: {config['mac_address']}")
            logger.info(f"    Poll Interval: {config['poll_interval']} seconds")
            logger.info(f"    Max Retries: {config['max_retries']}")
            logger.info(f"    Request Timeout: {config['request_timeout']}")
            logger.info(f"    Awake Request Timeout: {config['awake_request_timeout']}")
    
    serve(app, host='0.0.0.0', port=SERVER_PORT)
