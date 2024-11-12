import unittest
from unittest.mock import patch, Mock
import win32cred
from BranchBrowser import save_credentials, get_credentials


class TestCredentialsMethods(unittest.TestCase):

    @patch("win32cred.CredWrite")
    def test_save_credentials_success(self, mock_CredWrite):
        credential_name = "TestCredential"
        username = "TestUser"
        password = "TestPassword"

        save_credentials(credential_name, username, password)

        mock_CredWrite.assert_called_once_with({
            'Type': win32cred.CRED_TYPE_GENERIC,
            'TargetName': credential_name,
            'UserName': username,
            'CredentialBlob': password,
            'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE
        })

    @patch("win32cred.CredWrite", side_effect=Exception("Error saving credentials"))
    def test_save_credentials_failure(self, mock_CredWrite):
        credential_name = "TestCredential"
        username = "TestUser"
        password = "TestPassword"

        with self.assertRaises(Exception) as context:
            save_credentials(credential_name, username, password)

        self.assertEqual(str(context.exception), "Error saving credentials")

    @patch("win32cred.CredRead")
    def test_get_credentials_success(self, mock_CredRead):
        credential_name = "TestCredential"
        mock_CredRead.return_value = {
            'UserName': "TestUser",
            'CredentialBlob': "TestPassword".encode('utf-16')
        }

        username, password = get_credentials(credential_name)

        mock_CredRead.assert_called_once_with(credential_name, win32cred.CRED_TYPE_GENERIC)
        self.assertEqual(username, "TestUser")
        self.assertEqual(password, "TestPassword")

    @patch("win32cred.CredRead", side_effect=Exception("Credential not found"))
    def test_get_credentials_not_found(self, mock_CredRead):
        credential_name = "NonexistentCredential"

        username, password = get_credentials(credential_name)

        mock_CredRead.assert_called_once_with(credential_name, win32cred.CRED_TYPE_GENERIC)
        self.assertIsNone(username)
        self.assertIsNone(password)


if __name__ == "__main__":
    unittest.main()