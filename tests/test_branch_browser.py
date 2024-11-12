import unittest
from unittest.mock import patch, Mock
import win32cred
from BranchBrowser import save_credentials, get_credentials


class TestCredentialMethods(unittest.TestCase):
    CREDENTIAL_NAME = "TestCredential"
    USERNAME = "TestUser"
    PASSWORD = "TestPassword"
    NONEXISTENT_CREDENTIAL_NAME = "NonexistentCredential"
    ERROR_SAVING_CREDENTIALS_MESSAGE = "Error saving credentials"
    
    @patch("win32cred.CredWrite")
    def test_save_credentials_success(self, mock_CredWrite):
        save_credentials(self.CREDENTIAL_NAME, self.USERNAME, self.PASSWORD)

        mock_CredWrite.assert_called_once_with({
            'Type': win32cred.CRED_TYPE_GENERIC,
            'TargetName': self.CREDENTIAL_NAME,
            'UserName': self.USERNAME,
            'CredentialBlob': self.PASSWORD,
            'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE
        })

    @patch("win32cred.CredWrite", side_effect=Exception(ERROR_SAVING_CREDENTIALS_MESSAGE))
    def test_save_credentials_failure(self, mock_CredWrite):
        with self.assertRaises(Exception) as context:
            save_credentials(self.CREDENTIAL_NAME, self.USERNAME, self.PASSWORD)

        self.assertEqual(str(context.exception), self.ERROR_SAVING_CREDENTIALS_MESSAGE)

    @patch("win32cred.CredRead")
    def test_get_credentials_success(self, mock_CredRead):
        mock_CredRead.return_value = {
            'UserName': self.USERNAME,
            'CredentialBlob': self.PASSWORD.encode('utf-16')
        }

        username, password = get_credentials(self.CREDENTIAL_NAME)

        mock_CredRead.assert_called_once_with(self.CREDENTIAL_NAME, win32cred.CRED_TYPE_GENERIC)
        self.assertEqual(username, self.USERNAME)
        self.assertEqual(password, self.PASSWORD)

    @patch("win32cred.CredRead", side_effect=Exception("Credential not found"))
    def test_get_credentials_not_found(self, mock_CredRead):
        username, password = get_credentials(self.NONEXISTENT_CREDENTIAL_NAME)

        mock_CredRead.assert_called_once_with(self.NONEXISTENT_CREDENTIAL_NAME, win32cred.CRED_TYPE_GENERIC)
        self.assertIsNone(username)
        self.assertIsNone(password)


if __name__ == "__main__":
    unittest.main()