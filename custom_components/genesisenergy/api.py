"""Genesis Energy API."""

import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Any
from collections.abc import Mapping
import json
from urllib.parse import parse_qs

_LOGGER = logging.getLogger(__name__)

# http.client.HTTPConnection.debuglevel = 2
# logging.basicConfig()
# logging.getLogger().setLevel(logging.DEBUG)
# requests_log = logging.getLogger("requests.packages.urllib3")
# requests_log.setLevel(logging.DEBUG)
# requests_log.propagate = True

class GenesisEnergyApi:
    """Define the Genesis Energy API."""

    def __init__(self, email, password):
        """Initialise the API."""
        self._client_id = "8e41676f-7601-4490-9786-85d74f387f47"
        self._redirect_uri = 'https://myaccount.genesisenergy.co.nz/auth/redirect',
        self._url_token_base = "https://auth.genesisenergy.co.nz/auth.genesisenergy.co.nz"
        self._url_data_base = "https://web-api.genesisenergy.co.nz/"
        self._p = "B2C_1A_signin"

        self._email = email
        self._password = password

        self._accountNumber = None
        self._token = None
        self._refresh_token = None
        self._refresh_token_expires_in = 0
        self._access_token_expires_in = 0

    def get_setting_json(self, page: str) -> Mapping[str, Any] | None:
        """Get the settings from json result."""
        for line in page.splitlines():
            if line.startswith("var SETTINGS = ") and line.endswith(";"):
                # Remove the prefix and suffix to get valid JSON
                json_string = line.removeprefix("var SETTINGS = ").removesuffix(";")
                return json.loads(json_string)
        return None

    async def get_refresh_token(self):
        """Get the refresh token."""
        _LOGGER.debug("API get_refresh_token")

        async with aiohttp.ClientSession() as session:
            url = f"{self._url_token_base}/oauth2/v2.0/authorize"
            scope = f'openid offline_access {self._client_id}'
            params = {
                'p': self._p,
                'client_id': self._client_id,
                'response_type': 'code',
                'response_mode': 'query',
                'scope': scope,
                'redirect_uri': 'https://myaccount.genesisenergy.co.nz/auth/redirect',
            }

            _LOGGER.debug("Step: 1")
            async with session.get(url, params=params) as response:
                response_text = await response.text()

            settings_json = self.get_setting_json(response_text)
            trans_id = settings_json.get("transId")
            csrf = settings_json.get("csrf")

            url = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={trans_id}&p={self._p}"
            payload = {
                "request_type": "RESPONSE",
                "email": self._email,
            }
            headers = {
                'X-CSRF-TOKEN': csrf,
            }
            _LOGGER.debug("Step: 2")
            async with session.post(url, headers=headers, data=payload) as response:
                response_text = await response.text()
                pass


            url = f"{self._url_token_base}/{self._p}/api/SelfAsserted/confirmed"
            params = {
                'csrf_token': csrf,
                'tx': trans_id,
                'p': self._p,
            }
            _LOGGER.debug("Step: 3")
            async with session.get(url, params=params) as response:
                response_text = await response.text()
                # Extract the new CSRF token from cookies because it changes here
                csrf_value = response.cookies.get('x-ms-cpim-csrf').value
                csrf = csrf_value

            payload = {
                "request_type": "RESPONSE",
                "signInName": self._email,
                "password": self._password
            }

            headers = {
                'X-CSRF-TOKEN': csrf,
            }

            url = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={trans_id}&p={self._p}"
            _LOGGER.debug("Step: 4")
            async with session.post(url, headers=headers, data=payload) as response:
                pass

            url = f"{self._url_token_base}/{self._p}/api/CombinedSigninAndSignup/confirmed"
            params = {
                'rememberMe': 'false',
                'csrf_token': csrf,
                'tx': trans_id,
                'p': self._p
            }
            headers = {}
            _LOGGER.debug("Step: 5")
            async with session.get(url, headers=headers, params=params, allow_redirects=False) as response:
                response.raise_for_status()
                response_data = await response.text()

                location = response.headers.get('Location', '')
                query_params = parse_qs(location.split('?', 1)[1])
                if 'error' in query_params:
                    error = query_params['error'][0]
                    _LOGGER.error("Error in response: %s", error)
                    error_description = query_params['error_description'][0]
                    _LOGGER.error("Error description in response: %s", error_description)

            code = query_params['code'][0]
            url = f"{self._url_token_base}/{self._p}/oauth2/v2.0/token"
            params = {
                'p': self._p,
                'grant_type': 'authorization_code',
                'client_id': self._client_id,
                'scope': scope,
                'redirect_uri': self._redirect_uri,
                'code': code,
            }

            headers = {}
            async with session.get(url, headers=headers, params=params) as response:
                response_data = await response.json()
                refresh_token = response_data.get('refresh_token')
                access_token = response_data.get('access_token')
                refresh_token_expires_in = response_data.get('refresh_token_expires_in')
                access_token_expires_in = response_data.get('expires_in')

            self._token = access_token
            self._refresh_token = refresh_token
            self._refresh_token_expires_in = refresh_token_expires_in
            self._access_token_expires_in = access_token_expires_in
            _LOGGER.debug("Refresh token retrieved successfully")

    async def get_api_token(self):
        """Get token from the Genesis Energy API."""
        token_data = {
            "p": self._p,
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": self._refresh_token,
        }

        async with aiohttp.ClientSession() as session:
            url = f"{self._url_token_base}/oauth2/v2.0/token"
            async with session.post(url, data=token_data) as response:
                if response.status == 200:
                    jsonResult = await response.json()
                    self._token = jsonResult["access_token"]
                    _LOGGER.debug(f"Auth Token: {self._token}")
                else:
                    _LOGGER.error("Failed to retrieve the token page.")


    async def get_energy_data(self):
        """Get data from the API."""

        access_token_threshold = timedelta(minutes=5).total_seconds()
        if self._access_token_expires_in <= access_token_threshold:
            _LOGGER.warning("Access token needs renewing")
            await self.get_api_token()

        refresh_token_threshold = timedelta(minutes=5).total_seconds()
        if self._refresh_token_expires_in <= refresh_token_threshold:
            _LOGGER.warning("Refresh token needs renewing")
            await self.get_refresh_token()

        headers = {
            "authorization":  "Bearer " + self._token,
        }

        # API only returns 120 usage items (starting from the from_date).
        # If you want to query more than ~4 days of hourly data, at a time you need to split it into multiple requests
        # or the the latest usage will not be returned.
        to_date = datetime.now()
        from_date = to_date - timedelta(days=4) # fetch 4 days worth of data

        url = f"{self._url_data_base}/v2/private/electricity/site-usage"
        params = {
            'startDate': from_date.strftime("%Y-%m-%d"),
            'endDate': to_date.strftime("%Y-%m-%d"),
            'intervalType': "HOURLY"
        }

        async with aiohttp.ClientSession() as session, \
                session.post(url, headers=headers, json=params) as response:
            if response.status == 200:
                data = await response.json()
                # _LOGGER.debug(f"get_data returned data: {data}")
                if not data:
                    _LOGGER.warning("Fetched consumption successfully but there was no data")
                return data
            else:
                message = await response.text()
                _LOGGER.error("Could not fetch consumption, error: %s", message)
                return None
            

    async def get_gas_data(self):
        """Get data from the API."""

        access_token_threshold = timedelta(minutes=5).total_seconds()
        if self._access_token_expires_in <= access_token_threshold:
            _LOGGER.warning("Access token needs renewing")
            await self.get_api_token()

        refresh_token_threshold = timedelta(minutes=5).total_seconds()
        if self._refresh_token_expires_in <= refresh_token_threshold:
            _LOGGER.warning("Refresh token needs renewing")
            await self.get_refresh_token()

        headers = {
            "authorization":  "Bearer " + self._token,
        }

        # API only returns 120 usage items (starting from the from_date).
        # If you want to query more than ~4 days of hourly data, at a time you need to split it into multiple requests
        # or the the latest usage will not be returned.
        to_date = datetime.now()
        from_date = to_date - timedelta(days=4) # fetch 4 days worth of data

        url = f"{self._url_data_base}/v2/private/naturalgas/advanced/usage"
        params = {
            'startDate': from_date.strftime("%Y-%m-%d"),
            'endDate': to_date.strftime("%Y-%m-%d"),
            'intervalType': "HOURLY"
        }

        async with aiohttp.ClientSession() as session, \
                session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                # _LOGGER.debug(f"get_data returned data: {data}")
                if not data:
                    _LOGGER.warning("Fetched consumption successfully but there was no data")
                return data
            else:
                message = await response.text()
                _LOGGER.error("Could not fetch consumption, error: %s", message)
                return None
      
    async def get_powershout_balance(self):
        """Get data from the API."""

        access_token_threshold = timedelta(minutes=5).total_seconds()
        if self._access_token_expires_in <= access_token_threshold:
            _LOGGER.warning("Access token needs renewing")
            await self.get_api_token()

        refresh_token_threshold = timedelta(minutes=5).total_seconds()
        if self._refresh_token_expires_in <= refresh_token_threshold:
            _LOGGER.warning("Refresh token needs renewing")
            await self.get_refresh_token()

        headers = {
            "authorization":  "Bearer " + self._token,
        }

        url = f"{self._url_data_base}/v2/private/powershoutcurrency/balance"
        params = {
        }

        async with aiohttp.ClientSession() as session, \
                session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                # _LOGGER.debug(f"get_data returned data: {data}")
                if not data:
                    _LOGGER.warning("Fetched powershout balance successfully but there was no data")
                return data
            else:
                message = await response.text()
                _LOGGER.error("Could not fetch powershout balance, error: %s", message)
                return None