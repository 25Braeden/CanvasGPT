import requests


class CanvasAPIClient:
    def __init__(self, base_url, access_token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {access_token}"
        })

    def get(self, endpoint, params=None):
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"

        response = self.session.get(
            url,
            params=params,
            timeout=15
        )

        response.raise_for_status()
        return response.json()

    def get_active_courses(self):
        return self.get(
            "courses",
            params={
                "enrollment_state": "active",
                "per_page": 100,
            },
        )