import unittest

from app.security import totp_code, totp_verify


class TotpInputTests(unittest.TestCase):
    SECRET = 'JBSWY3DPEHPK3PXP'

    def test_unicode_digits_are_rejected_without_raising(self):
        for code in ['١٢٣٤٥٦', '１２３４５６', '²²²²²²']:
            with self.subTest(code=code):
                self.assertFalse(totp_verify(self.SECRET, code, at=1800000000))

    def test_valid_ascii_code_still_verifies(self):
        self.assertTrue(totp_verify(self.SECRET, totp_code(self.SECRET, at=1800000000), at=1800000000))


if __name__ == '__main__':
    unittest.main()
