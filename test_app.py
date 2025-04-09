import unittest
from unittest.mock import patch, MagicMock, mock_open, ANY
from app import app, send_wol_packet, is_server_awake, get_service_configs
import requests
import os
import yaml
import io
import logging
import time

class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        log_level = os.getenv('LOG_LEVEL', 'WARNING')
        logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    def setUp(self):
        app.service_configs = get_service_configs()
        self.app = app.test_client()
        self.app.testing = True
        self.test_host = "configured-service.example.com"
        self.test_url = "http://example.com"
        self.test_mac = "00:11:22:33:44:55"
        
    @patch('app.requests.request')
    def test_is_server_awake_success(self, mock_request):
        mock_response = MagicMock(status_code=200)
        mock_request.return_value = mock_response
        url = "http://example.com"
        is_awake = is_server_awake(url, timeout=5)
        self.assertTrue(is_awake)
        mock_request.assert_called_with(
            method='GET',
            url=url,
            timeout=5
        )

    @patch('app.requests.request')
    def test_is_server_awake_failure(self, mock_request):
        mock_request.side_effect = requests.RequestException("Connection error")
        url = "http://example.com"
        is_awake = is_server_awake(url, timeout=5)
        self.assertFalse(is_awake)

    @patch('app.os.path.exists')
    @patch('app.open', new_callable=mock_open)
    @patch('app.yaml.safe_load')
    def test_get_service_configs_from_yaml(self, mock_yaml_load, mock_file, mock_exists):
        mock_exists.return_value = True
        yaml_config = {
            "service1.example.com": {
                "base_url": "http://service1.local",
                "awake_check_endpoint": "/health",
                "mac_address": "00:11:22:33:44:55",
                "poll_interval": 3,
                "max_retries": 5,
                "request_timeout": 10,
                "awake_request_timeout": 8
            }
        }
        mock_yaml_load.return_value = yaml_config
        
        # Clear environment variables that might affect the test
        with patch.dict(os.environ, {}, clear=True):
            configs = get_service_configs()
            
        self.assertIn("service1.example.com", configs)
        service_config = configs["service1.example.com"]
        self.assertEqual(service_config["base_url"], "http://service1.local")
        self.assertEqual(service_config["awake_check_endpoint"], "/health")
        self.assertEqual(service_config["mac_address"], "00:11:22:33:44:55")
        self.assertEqual(service_config["poll_interval"], 3)
        self.assertEqual(service_config["max_retries"], 5)
        self.assertEqual(service_config["request_timeout"], 10)
        self.assertEqual(service_config["awake_request_timeout"], 8)

    @patch('app.os.path.exists')
    def test_get_service_configs_from_env(self, mock_exists):
        mock_exists.return_value = False
        
        env_vars = {
            'SERVICE_TEST.EXAMPLE.COM_BASE_URL': 'http://test.local',
            'SERVICE_TEST.EXAMPLE.COM_AWAKE_CHECK_ENDPOINT': '/status',
            'SERVICE_TEST.EXAMPLE.COM_MAC_ADDRESS': '11:22:33:44:55:66',
            'SERVICE_TEST.EXAMPLE.COM_POLL_INTERVAL': '2',
            'SERVICE_TEST.EXAMPLE.COM_MAX_RETRIES': '3',
            'SERVICE_TEST.EXAMPLE.COM_REQUEST_TIMEOUT': '7',
            'SERVICE_TEST.EXAMPLE.COM_AWAKE_REQUEST_TIMEOUT': '4'
        }
        
        # Clear environment variables that might affect the test
        with patch.dict(os.environ, env_vars):
            configs = get_service_configs()
            
        self.assertIn("test.example.com", configs)
        service_config = configs["test.example.com"]
        self.assertEqual(service_config["base_url"], "http://test.local")
        self.assertEqual(service_config["awake_check_endpoint"], "/status")
        self.assertEqual(service_config["mac_address"], "11:22:33:44:55:66")
        self.assertEqual(service_config["poll_interval"], 2)
        self.assertEqual(service_config["max_retries"], 3)
        self.assertEqual(service_config["request_timeout"], 7)
        self.assertEqual(service_config["awake_request_timeout"], 4)

    @patch('app.os.path.exists')
    def test_get_service_configs_from_env_underscore_in_host(self, mock_exists):
        mock_exists.return_value = False
        
        env_vars = {
            'SERVICE_TEST_WAKE.EXAMPLE.COM_BASE_URL': 'http://test.local',
            'SERVICE_TEST_WAKE.EXAMPLE.COM_AWAKE_CHECK_ENDPOINT': '/status',
            'SERVICE_TEST_WAKE.EXAMPLE.COM_MAC_ADDRESS': '11:22:33:44:55:66',
            'SERVICE_TEST_WAKE.EXAMPLE.COM_POLL_INTERVAL': '2',
            'SERVICE_TEST_WAKE.EXAMPLE.COM_MAX_RETRIES': '3',
            'SERVICE_TEST_WAKE.EXAMPLE.COM_REQUEST_TIMEOUT': '7',
            'SERVICE_TEST_WAKE.EXAMPLE.COM_AWAKE_REQUEST_TIMEOUT': '4'
        }
        
        # Clear environment variables that might affect the test
        with patch.dict(os.environ, env_vars):
            configs = get_service_configs()
            
        self.assertIn("test_wake.example.com", configs)
        service_config = configs["test_wake.example.com"]
        self.assertEqual(service_config["base_url"], "http://test.local")
        self.assertEqual(service_config["awake_check_endpoint"], "/status")
        self.assertEqual(service_config["mac_address"], "11:22:33:44:55:66")
        self.assertEqual(service_config["poll_interval"], 2)
        self.assertEqual(service_config["max_retries"], 3)
        self.assertEqual(service_config["request_timeout"], 7)
        self.assertEqual(service_config["awake_request_timeout"], 4)

    @patch('app.os.path.exists')
    def test_get_service_configs_no_config_found(self, mock_exists):
        """Test that an empty config dict is returned if no YAML or ENV vars are found."""
        mock_exists.return_value = False

        # Clear environment variables that might define services
        # We need to preserve other env vars potentially needed by the test runner or system
        original_environ = os.environ.copy()
        keys_to_remove = [k for k in original_environ if k.startswith('SERVICE_')]
        for k in keys_to_remove:
            del os.environ[k]

        try:
            configs = get_service_configs()
            self.assertEqual(configs, {})
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(original_environ)


    @patch('app.os.path.exists')
    @patch('app.open', new_callable=mock_open)
    @patch('app.yaml.safe_load')
    def test_env_vars_override_yaml_config(self, mock_yaml_load, mock_file, mock_exists):
        mock_exists.return_value = True
        yaml_config = {
            "service1.example.com": {
                "base_url": "http://service1.local",
                "awake_check_endpoint": "/health",
                "mac_address": "00:11:22:33:44:55",
                "poll_interval": 3,
                "max_retries": 5
            }
        }
        mock_yaml_load.return_value = yaml_config
        
        env_vars = {
            'SERVICE_SERVICE1.EXAMPLE.COM_BASE_URL': 'http://override.local',
            'SERVICE_SERVICE1.EXAMPLE.COM_MAC_ADDRESS': '99:88:77:66:55:44',
            'SERVICE_SERVICE1.EXAMPLE.COM_POLL_INTERVAL': '10'
        }
        
        with patch.dict(os.environ, env_vars):
            configs = get_service_configs()
            
        self.assertIn("service1.example.com", configs)
        service_config = configs["service1.example.com"]
        self.assertEqual(service_config["base_url"], "http://override.local")
        self.assertEqual(service_config["mac_address"], "99:88:77:66:55:44")
        self.assertEqual(service_config["poll_interval"], 10)

    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": None,
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.requests.request')
    def test_proxy_request_success(self, mock_request, mock_send_wol):
        mock_response = MagicMock(status_code=200, headers={'Content-Type': 'text/plain'})
        mock_response.iter_content.return_value = iter([b'OK'])
        mock_request.return_value = mock_response
        response = self.app.get('/', headers={"Host": self.test_host})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'OK')
        mock_send_wol.assert_not_called()

        called_args = mock_request.call_args
        self.assertEqual(called_args[1]['timeout'], 5)

    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": None,
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.requests.request')
    def test_proxy_request_with_path(self, mock_request, mock_send_wol):
        mock_response = MagicMock(status_code=200, headers={'Content-Type': 'text/plain'})
        mock_response.iter_content.return_value = iter([b'OK']) # Assuming 'OK' is the expected content, adjust if needed
        mock_request.return_value = mock_response
        response = self.app.get('/api/resource', headers={"Host": self.test_host})
        self.assertEqual(response.status_code, 200)
        # Allow any headers since Flask adds its own headers
        called_args = mock_request.call_args
        self.assertEqual(called_args[1]['method'], 'GET')
        self.assertEqual(called_args[1]['url'], 'http://example.com/api/resource')
        self.assertEqual(called_args[1]['data'], b'')
        self.assertEqual(called_args[1]['timeout'], 5)

    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": None,
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.requests.request')
    def test_proxy_post_request(self, mock_request, mock_send_wol):
        """Test that POST requests and their data are proxied."""
        mock_response = MagicMock(status_code=201, headers={'Content-Type': 'text/plain'})
        mock_response.iter_content.return_value = iter([b'Created'])
        mock_request.return_value = mock_response
        post_data = b'{"key": "value"}'
        response = self.app.post('/api/create', headers={"Host": self.test_host, "Content-Type": "application/json"}, data=post_data)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, b'Created')
        mock_send_wol.assert_not_called() # Assuming server is initially awake for this test

        called_args = mock_request.call_args
        self.assertEqual(called_args[1]['method'], 'POST')
        self.assertEqual(called_args[1]['url'], 'http://example.com/api/create')
        self.assertEqual(called_args[1]['data'], post_data)
        # Check that relevant headers are passed (Content-Type is important for POST)
        self.assertIn('Content-Type', called_args[1]['headers'])
        self.assertEqual(called_args[1]['headers']['Content-Type'], 'application/json')
        self.assertEqual(called_args[1]['timeout'], 5)

    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": None,
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.requests.request')
    def test_proxy_get_request_with_query_params(self, mock_request, mock_send_wol):
        """Test that GET requests with query parameters are proxied correctly."""
        mock_response = MagicMock(status_code=200, headers={'Content-Type': 'text/plain'})
        mock_response.iter_content.return_value = iter([b'Search Results'])
        mock_request.return_value = mock_response
        query_string = 'q=test&limit=10'
        response = self.app.get(f'/api/search?{query_string}', headers={"Host": self.test_host})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'Search Results')
        mock_send_wol.assert_not_called() # Assuming server is initially awake

        called_args = mock_request.call_args
        self.assertEqual(called_args[1]['method'], 'GET')
        self.assertEqual(called_args[1]['url'], f'http://example.com/api/search?{query_string}')
        self.assertEqual(called_args[1]['data'], b'') # GET requests shouldn't have data in the body
        self.assertEqual(called_args[1]['timeout'], 5)


    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": None,
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.requests.request')
    @patch('time.sleep', return_value=None)
    def test_proxy_request_failure_and_retry_success(self, mock_sleep, mock_request, mock_send_wol):
        # Simulate the sequence of requests:
        # 1. is_server_awake check fails (using base_url as no awake_check_endpoint)
        # 2. is_server_awake check succeeds after WoL/sleep
        # 3. Actual proxy request succeeds
        mock_request.side_effect = [
            requests.RequestException("Connection error"), # First awake check fails
            MagicMock(status_code=200), # Second awake check succeeds
            MagicMock(status_code=200, headers={'Content-Type': 'text/plain'}, iter_content=MagicMock(return_value=iter([b'OK']))) # Final proxy request succeeds
        ]

        response = self.app.get('/', headers={"Host": self.test_host})
        
        mock_send_wol.assert_called_once_with("00:11:22:33:44:55")
        mock_sleep.assert_called_once_with(0.1) # From the patched service_configs

        # Verify the calls to requests.request with correct timeouts
        self.assertEqual(mock_request.call_count, 3)
        call_args_list = mock_request.call_args_list

        # Call 1: First is_server_awake check (should use awake_request_timeout)
        self.assertEqual(call_args_list[0][1]['url'], 'http://example.com') # Base URL used for awake check
        self.assertEqual(call_args_list[0][1]['timeout'], 5) # awake_request_timeout from config

        # Call 2: Second is_server_awake check (should use awake_request_timeout)
        self.assertEqual(call_args_list[1][1]['url'], 'http://example.com')
        self.assertEqual(call_args_list[1][1]['timeout'], 5)

        # Call 3: Final proxy request (should use request_timeout)
        self.assertEqual(call_args_list[2][1]['url'], 'http://example.com/')
        self.assertEqual(call_args_list[2][1]['timeout'], 5)

        self.assertEqual(response.status_code, 200)

    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": None,
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.is_server_awake')
    def test_proxy_request_failure_and_retry_failure(self, mock_is_server_awake, mock_send_wol):
        mock_is_server_awake.return_value = False
        
        response = self.app.get('/', headers={"Host": self.test_host})
        self.assertEqual(response.status_code, 503)
        mock_send_wol.assert_called_once()

    @patch('app.service_configs', {
        "configured-service.example.com": {
            "base_url": "http://example.com",
            "awake_check_endpoint": "/health",
            "mac_address": "00:11:22:33:44:55",
            "poll_interval": 0.1,
            "max_retries": 1,
            "request_timeout": 5,
            "awake_request_timeout": 5
        }
    })
    @patch('app.send_wol_packet')
    @patch('app.is_server_awake')
    @patch('app.requests.request')
    def test_proxy_request_with_awake_check_endpoint(self, mock_request, mock_is_server_awake, mock_send_wol):
        mock_is_server_awake.side_effect = [False, True]
        mock_response = MagicMock(status_code=200, headers={'Content-Type': 'text/plain'})
        mock_response.iter_content.return_value = iter([b'OK'])
        mock_request.return_value = mock_response
        
        response = self.app.get('/api/data', headers={"Host": self.test_host})
        
        mock_is_server_awake.assert_any_call('http://example.com/health', 5)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'OK')

    def test_proxy_request_missing_host_header(self):
        # Create a test client with a custom environ
        with app.test_request_context('/'):
            # Directly test the function with a mocked request
            with patch('app.request.headers.get', return_value=None):
                with patch('app.service_configs', {}):
                    from app import proxy_request
                    response = proxy_request('')
                    self.assertEqual(response[1], 400)  # Check status code
                    self.assertIn("Host header is missing", response[0])  # Check message

    def test_proxy_request_unknown_host(self):
        with patch('app.service_configs', {}):
            response = self.app.get('/', headers={"Host": "unknown.example.com"})
            self.assertEqual(response.status_code, 404)
            self.assertIn(b'Unknown target service', response.data)

if __name__ == '__main__':
    unittest.main()
