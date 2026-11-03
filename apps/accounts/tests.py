from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse


class CsrfTokenRotationTests(TestCase):
    def test_current_cookie_token_works_after_login_rotates_csrf_secret(self):
        user = get_user_model().objects.create_user(username='csrf-user', password='secret123')
        client = Client(enforce_csrf_checks=True)

        login_page = client.get(reverse('accounts:login'))
        stale_token = login_page.cookies['csrftoken'].value
        login_response = client.post(reverse('accounts:login'), {
            'username': user.username,
            'password': 'secret123',
            'csrfmiddlewaretoken': stale_token,
        })

        self.assertEqual(login_response.status_code, 302)
        fresh_token = client.cookies['csrftoken'].value
        self.assertNotEqual(stale_token, fresh_token)

        stale_post = client.post(reverse('accounts:logout'), {
            'csrfmiddlewaretoken': stale_token,
        })
        self.assertEqual(stale_post.status_code, 403)

        fresh_post = client.post(reverse('accounts:logout'), {
            'csrfmiddlewaretoken': fresh_token,
        })
        self.assertEqual(fresh_post.status_code, 302)