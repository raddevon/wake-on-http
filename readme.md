# Wake on HTTP 🥱

## Overview
Wake on HTTP is a Dockerized HTTP proxy that proxies a request to a system that may not be powered on. If the machine does not respond to an awake request, the proxy will send a wake-on-LAN magic packet and continue checking for awakeness. Once the machine is awake, Wake on HTTP will proxy the request through to the target and return the response.

## Setup Instructions

### High-Level
At a high level, here's how you will set up and use Wake on HTTP:

1. Configure wake-on-LAN on a machine hosting some service you want to be able to access on-demand.
2. Bring up a Wake on HTTP Docker container, configuring as many services as you want to be able to proxy to. Provide at least a host, base URL, awake check endpoint, and MAC address.
3. Configure a reverse proxy on an always-on machine to proxy requests on a host (individual or wildcard) to your Wake on HTTP container.
4. When accessing a service on the possibly powered off, use the host you configured in Wake on HTTP instead of the direct host or IP.

If everything is configured properly, Wake on HTTP will proxy requests to the target service after waking the machine (if necessary).

Configuring wake-on-LAN is outside the scope of this document and accessing via the configured host is pretty straightforward, but let's dive into the other two steps: bringing up the container with service configurations and configuring a reverse-proxy.

### Configuration

#### Services Configuration
**Services** are individual targets to which you may proxy requests through Wake on HTTP.

You may configure services either via a `services.yaml` file or using environment variables. If the same service (i.e., a service with a common host) is configured in both environment variables and in `services.yaml`, the environment variable configuration will take precedence. Individual service config values can also be overridden via environment variables.

1. **Using `services.yaml`**:
   - Create a `services.yaml` file with the following structure:
     ```yaml
     media.wake.mydomain.com:
       base_url: http://192.168.1.48:3000
       awake_check_endpoint: /health
       mac_address: FF:FF:FF:FF:FF:FF
       poll_interval: 3
       max_retries: 15
       request_timeout: 15
       awake_request_timeout: 3
     photos.wake.mydomain.com:
       base_url: http://192.168.1.115:8080
       awake_check_endpoint: /api/version
       mac_address: AA:BB:CC:DD:EE:FF
     ```
   
   Bind this file as a Docker volume at `/config/services.yaml` on the container or specify a different path on the container by setting `SERVICES_CONFIG_PATH`.

   The example above defines two services. To illustrate how configuration maps to the proxy algorithm, I'll describe one of them. The first service matches requests with a `Host` header value of `media.wake.mydomain.com`. Before sending the proxied request, Wake on HTTP will check for awakeness by sending up to 15 requests (number specified by `max_retries`) to `http://192.168.1.48:3000/health` (`base_url` + `awake_check_endpoint`) with 3 seconds between attempts (interval specified by `poll_interval`) and a timeout on each attempt of 3 seconds (specified by `awake_request_timeout`). If the service is not awake and does not respond to an awake test attempt, a magic packet will be sent to `FF:FF:FF:FF:FF:FF` before the next attempt. Once an awake check attempt succeeds (i.e., returns a good response code), the request will be proxied and the response returned unless it takes more than 15 seconds to respond (specified by `request_timeout`).

   **Service Configuration Options in YAML**:
   - The top-level key in the YAML should be the hostname that will be matched against the incoming request's `Host` header
   - `base_url`: The base URL of the target service
   - `awake_check_endpoint`: A specific endpoint to check if the server is awake. This should be a simple endpoint that will return a response quickly when the service is up.
   - `mac_address`: The MAC address of the target system for sending Wake-on-LAN magic packets
   - `poll_interval`: (Optional) Time in seconds between wake attempts (defaults to `GLOBAL_POLL_INTERVAL`)
   - `max_retries`: (Optional) Maximum number of wake attempts (defaults to `GLOBAL_MAX_RETRIES`)
   - `request_timeout`: (Optional) Timeout for the actual request after the server is awake (defaults to `GLOBAL_REQUEST_TIMEOUT`)
   - `awake_request_timeout`: (Optional) Timeout for the server awake check request (defaults to `GLOBAL_AWAKE_REQUEST_TIMEOUT`, which defaults to `GLOBAL_REQUEST_TIMEOUT`)

2. **Using Environment Variables**:
   - Set environment variables for each service. For example, to configure a service named `media`, you would set:
     ```
     SERVICE_MEDIA.WAKE.MYDOMAIN.COM_BASE_URL=http://192.168.1.48:3000
     SERVICE_MEDIA.WAKE.MYDOMAIN.COM_AWAKE_CHECK_ENDPOINT=/health
     SERVICE_MEDIA.WAKE.MYDOMAIN.COM_MAC_ADDRESS=FF:FF:FF:FF:FF:FF
     ```

   **Environment Variable Format**:
   - `SERVICE_<host>_BASE_URL`: The base URL of the target service
   - `SERVICE_<host>_AWAKE_CHECK_ENDPOINT`: A specific endpoint to check if the server is awake
   - `SERVICE_<host>_MAC_ADDRESS`: The MAC address of the target system for sending Wake-on-LAN magic packets
   - `SERVICE_<host>_POLL_INTERVAL`: (Optional) Time in seconds between wake attempts
   - `SERVICE_<host>_MAX_RETRIES`: (Optional) Maximum number of wake attempts
   - `SERVICE_<host>_REQUEST_TIMEOUT`: (Optional) Timeout for the actual request after the server is awake
   - `SERVICE_<host>_AWAKE_REQUEST_TIMEOUT`: (Optional) Timeout for the server awake check request

#### Global Environment Variables
- `SERVER_PORT`: Port to run the proxy server on (default: `3000`)
- `SERVICES_CONFIG_PATH`: Path on the container to the services configuration file (default: `/config/services.yaml`). Bind this file or the containing directory as a volume in your Docker config to persist the file and make it easy to edit from your host.
- `LOG_LEVEL`: Logging level (default: `INFO`)
  - Options:
  - `ERROR`- Least verbose. Logs only errors.
  - `WARN`- Logs warnings, which may not always indicate an issue.
  - `INFO`- Logs key updates about the status of the app.
  - `DEBUG`- Most verbose. Logs many details about the status of the app.
  - Each subsequent logging level logs all the log messages of the levels above it.
- `GLOBAL_POLL_INTERVAL`: Poll interval in seconds for checking server status after sending a WOL packet (default: `5`)
- `GLOBAL_MAX_RETRIES`: Maximum number of retries before giving up on waking up the server (default: `10`)
- `GLOBAL_REQUEST_TIMEOUT`: Timeout for the final HTTP request in seconds (default: `5`)
- `GLOBAL_AWAKE_REQUEST_TIMEOUT`: Timeout for server awake check requests in seconds (defaults to the same value as `GLOBAL_REQUEST_TIMEOUT`)

Environment variables can be set for the container by passing them to a `docker run` command with the `-e` switch or in the docker-compose file's `environment` section. See below for examples.

### Running the Application

#### Using Docker
1. **Pull the Docker image from a container registry**:
   ```sh
   docker pull ghcr.io/raddevon/wake-on-http:latest
   ```

2. **Run the Docker container with network access to other systems on the host's network**:
   - **Using Host Networking**: This is the simplest method and recommended for most users.
     ```sh
     docker run -d \
       --network host \
       -e SERVICE_MEDIA.WAKE.MYDOMAIN.COM_BASE_URL=http://192.168.1.48:3000 \
       -e SERVICE_MEDIA.WAKE.MYDOMAIN.COM_MAC_ADDRESS=FF:FF:FF:FF:FF:FF \
       -e SERVICE_MEDIA.WAKE.MYDOMAIN.COM_AWAKE_CHECK_ENDPOINT=/health \
       ghcr.io/raddevon/wake-on-http:latest
     ```

     with Docker Compose:

     ```yaml
     services:
       wake-on-http:
         image: ghcr.io/raddevon/wake-on-http:latest
         network_mode: host
         environment:
           SERVICE_MEDIA.WAKE.MYDOMAIN.COM_BASE_URL: http://192.168.1.48:3000
           SERVICE_MEDIA.WAKE.MYDOMAIN.COM_MAC_ADDRESS: FF:FF:FF:FF:FF:FF
           SERVICE_MEDIA.WAKE.MYDOMAIN.COM_AWAKE_CHECK_ENDPOINT: /health
         restart: always
     ```
   - **Using Macvlan Networking**: This method allows the container to appear as a separate device on the same physical network as the host.
     ```sh
     docker network create -d macvlan \
       --subnet=192.168.1.0/24 \
       --gateway=192.168.1.1 \
       -o parent=eth0 \
       my_macvlan_network

     docker run -d \
       --network my_macvlan_network \
       --ip 192.168.1.100 \  # Optional: Assign a specific IP
       -e SERVICE_MEDIA.WAKE.MYDOMAIN.COM_BASE_URL=http://192.168.1.48:3000 \
       -e SERVICE_MEDIA.WAKE.MYDOMAIN.COM_MAC_ADDRESS=FF:FF:FF:FF:FF:FF \
       -e SERVICE_MEDIA.WAKE.MYDOMAIN.COM_AWAKE_CHECK_ENDPOINT=/health \
       ghcr.io/raddevon/wake-on-http:latest
     ```

    with Docker Compose:
       
     ```yaml
     services:
       wol-proxy:
         image: ghcr.io/raddevon/wake-on-http:latest
         networks:
           my_macvlan_network:
             ipv4_address: 192.168.1.100  # Optional: Assign a specific IP
         environment:
           SERVICE_MEDIA.WAKE.MYDOMAIN.COM_HOST: media.wake.mydomain.com
           SERVICE_MEDIA.WAKE.MYDOMAIN.COM_BASE_URL: http://192.168.1.48:3000
           SERVICE_MEDIA.WAKE.MYDOMAIN.COM_MAC_ADDRESS: FF:FF:FF:FF:FF:FF
     
     networks:
       my_macvlan_network:
         driver: macvlan
         driver_opts:
           parent: eth0  # Replace with your host's network interface name
         ipam:
           config:
             - subnet: 192.168.1.0/24
               gateway: 192.168.1.1
     ```
     To run the service using Docker Compose:
     ```sh
     docker-compose up -d
     ```

### Reverse Proxy Configuration

When configuring a reverse proxy, it is convenient to configure a wildcard host for the Wake on HTTP configuration if you will have multiple services proxied through it. This also makes it very easy to add services without touching your reverse proxy configuration.

Your use case may not work with this model though, so you can also configure individual hosts. I'll demonstrate both in a few popular HTTP servers.

#### Caddy
##### Wildcard Host (`*.wake.mydomain.com`)
```caddyfile
*.wake.mydomain.com {
    reverse_proxy localhost:3000
}
```

> [!IMPORTANT]  
> If you're like me, you may have been using Caddy's handy automatic SSL without ever configuring [DNS challenges](https://caddyserver.com/docs/automatic-https#dns-challenge). If that's the case, you'll want to read up on this as it will be required to obtain a SSL certificate for your wildcard host. It can be a bit of a pain, so that may be reason enough for you to use the individual hosts method below.

##### Individual Hosts (`media.wake.mydomain.com`, `photos.wake.mydomain.com`)
```caddyfile
media.wake.mydomain.com {
    reverse_proxy localhost:3000
}

photos.wake.mydomain.com {
    reverse_proxy localhost:3000
}
```

#### Traefik
##### Wildcard Host (`*.wake.mydomain.com`)
Assuming you are using Traefik with Docker labels, you can use the following configuration:
```yaml
services:
  wol-proxy:
    image: ghcr.io/raddevon/wake-on-http:latest
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.wol-proxy.rule=HostRegexp(`{subdomain}.wake.mydomain.com`)"
      - "traefik.http.services.wol-proxy.loadbalancer.server.port=3000"

  # Other services...
```

> [!IMPORTANT]  
> I'm guessing Traefik will require DNS challenge configuration for the wildcard host configuration method, but since I don't use Traefik myself, I don't know exactly what that entails. If you use Traefik and end up configuring this, it would be awesome if you would submit a PR to update this message with relevant links that might help other Traefik users in the future.

##### Individual Hosts (`media.wake.mydomain.com`, `photos.wake.mydomain.com`)
```yaml
services:
  wol-proxy:
    image: ghcr.io/raddevon/wake-on-http:latest
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.media.rule=Host(`media.wake.mydomain.com`)"
      - "traefik.http.services.media.loadbalancer.server.port=3000"
      - "traefik.http.routers.photos.rule=Host(`photos.wake.mydomain.com`)"
      - "traefik.http.services.photos.loadbalancer.server.port=3000"

  # Other services...
```

#### Nginx
##### Wildcard Host (`*.wake.mydomain.com`)
Nginx does not natively support wildcard subdomains in the `server_name` directive, but you can use a map to achieve this:
```nginx
map $http_host $is_wake_domain {
    ~^(?<subdomain>.+)\.wake\.mydomain\.com$ 1;
    default 0;
}

server {
    listen 80;

    if ($is_wake_domain) {
        proxy_pass http://localhost:3000;
        break;
    }

    return 404;
}
```

##### Individual Hosts (`media.wake.mydomain.com`, `photos.wake.mydomain.com`)
```nginx
server {
    listen 80;
    server_name media.wake.mydomain.com;

    location / {
        proxy_pass http://localhost:3000;
    }
}

server {
    listen 80;
    server_name photos.wake.mydomain.com;

    location / {
        proxy_pass http://localhost:3000;
    }
}
```

### Testing

To run tests, use the following command:
```sh
python -m unittest discover
```

## License
GPL License