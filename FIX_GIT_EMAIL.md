# Fix Git Email Configuration

## Issue
Your commits show `kalvintousant@example.com` which is a placeholder email.
GitHub requires verified email addresses and may suspend accounts with unverified emails.

## Fix Commands

### For this repository:
```bash
cd "/Users/kalvintousant/Desktop/Kalshi Trader Bot"
git config user.email "your-real-email@domain.com"
git config user.name "Your Real Name"
```

### For all repositories (global):
```bash
git config --global user.email "your-real-email@domain.com"
git config --global user.name "Your Real Name"
```

### Verify it worked:
```bash
git config user.email
git config user.name
```

## Important Notes
- Use the SAME email address that's verified on your GitHub account
- Check your GitHub email settings: https://github.com/settings/emails
- After fixing, future commits will use the correct email
- Past commits will still show old email (can't change history without rewriting)

## After Fixing
1. Contact GitHub support to appeal suspension
2. Explain that email was placeholder and is now fixed
3. Request account restoration
