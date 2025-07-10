# Google OAuth Setup Guide

This guide will walk you through setting up Google OAuth authentication for your climbing webapp.

## 📋 Prerequisites

Before starting, ensure you have:
- A Google account
- Access to [Google Cloud Console](https://console.cloud.google.com/)
- Your climbing webapp running locally or deployed

## 🚀 Quick Start

### 1. Install Dependencies

First, install the new dependencies:

```bash
# If using uv (recommended)
uv sync

# Or if using pip
pip install python-jose[cryptography] passlib[bcrypt] python-dotenv itsdangerous
```

### 2. Create Environment File

Copy the template and fill in your values:

```bash
cp .env.template .env
```

Then edit `.env` with your actual values (see sections below).

### 3. Google Cloud Console Setup

#### A. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "New Project" or select existing project
3. Enter project name (e.g., "climbing-app-oauth")
4. Note your Project ID

#### B. Enable Required APIs

1. Navigate to "APIs & Services" → "Enabled APIs & services"
2. Click "+ ENABLE APIS AND SERVICES"
3. Search for and enable: **"People API"** or **"Google+ API"**

#### C. Configure OAuth Consent Screen

1. Go to "APIs & Services" → "OAuth consent screen"
2. Choose "External" user type (unless you have Google Workspace)
3. Fill in required fields:
   - App name: "Climbing App"
   - User support email: your email
   - Developer contact information: your email
4. Add scopes:
   - `../auth/userinfo.email`
   - `../auth/userinfo.profile`
   - `openid`
5. Add test users (emails of people who can use the app during development)
6. Save and continue

#### D. Create OAuth Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "+ CREATE CREDENTIALS" → "OAuth 2.0 Client IDs"
3. Application type: **Web application**
4. Name: "Climbing App Web Client"
5. **Authorized redirect URIs**: Add these URLs:
   - Development: `http://localhost:8000/auth/callback`
   - Production: `https://yourdomain.com/auth/callback`
6. Click "Create"
7. **Copy the Client ID and Client Secret**

### 4. Configure Environment Variables

Edit your `.env` file:

```env
# From Google Cloud Console OAuth credentials
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here

# Generate a secure secret key
SECRET_KEY=your_secret_key_for_sessions_here

# Your app's base URL
BASE_URL=http://localhost:8000

# Environment
ENVIRONMENT=development
```

#### Generate Secret Key

Run this command to generate a secure secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output to your `SECRET_KEY` in `.env`.

### 5. Start Your Application

```bash
# If using uvicorn directly
uvicorn main:app --reload

# Or if you have a start script
./start.sh
```

### 6. Test OAuth Flow

1. Open your webapp (usually `http://localhost:8000`)
2. You should see a "Login with Google" button in the navigation
3. Click it and follow the OAuth flow
4. After successful login, you should see your profile dropdown

## 🔧 Configuration Options

### Production Setup

For production deployment:

1. **Use HTTPS**: OAuth requires secure connections in production
2. **Update redirect URIs**: Add your production domain to Google Console
3. **Set environment variables**:
   ```env
   BASE_URL=https://yourdomain.com
   ENVIRONMENT=production
   ```
4. **Secure your secrets**: Use proper secret management (not `.env` files)

### Security Considerations

- **Never commit `.env` files** to version control
- **Use HTTPS in production** - OAuth requires secure connections
- **Regularly rotate your SECRET_KEY**
- **Keep CLIENT_SECRET secure** - never expose in frontend code
- **Use minimal scopes** - only request email and profile access

## 🎨 Customization

### UI Customization

The login button and user dropdown are styled with CSS classes in `static/css/styles.css`:
- `.login-btn` - Google login button
- `.user-profile-dropdown` - User profile dropdown
- `.profile-dropdown-menu` - Dropdown menu

### Permission System

Optional: Use the `user_integration.py` file to link OAuth users with your crew system:

```python
from user_integration import get_enhanced_user_data, can_user_access_resource

# In your route
enhanced_user = get_enhanced_user_data(oauth_user)
if can_user_access_resource(enhanced_user, "albums", "submit"):
    # User can submit albums
```

### Frontend Integration

The `auth.js` file provides:
- Automatic login/logout button management
- User profile display
- Authentication state checking
- Error handling

Use these data attributes in your HTML:
- `data-auth-required="true"` - Show only when authenticated
- `data-auth-required="false"` - Show only when not authenticated
- `data-user-name` - Will be filled with user's name
- `data-user-email` - Will be filled with user's email
- `data-user-avatar` - Will be set to user's profile picture

## 🐛 Troubleshooting

### Common Issues

1. **"OAuth not configured" error**
   - Check that `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set in `.env`
   - Verify the `.env` file is in the same directory as `main.py`

2. **"Redirect URI mismatch" error**
   - Ensure redirect URI in Google Console matches exactly: `http://localhost:8000/auth/callback`
   - Check for trailing slashes or http vs https

3. **"This app isn't verified" warning**
   - Normal for development apps
   - Click "Advanced" → "Go to [app name] (unsafe)" to continue
   - For production, submit for Google verification

4. **Session not persisting**
   - Check that `SECRET_KEY` is set and not changing between restarts
   - Verify cookies are enabled in browser

5. **"Failed to exchange authorization code"**
   - Check that `CLIENT_SECRET` is correct
   - Verify your Google Cloud project has the correct APIs enabled

### Debug Mode

Enable debug logging by setting log level to DEBUG in your `main.py`:

```python
logging.getLogger().setLevel(logging.DEBUG)
```

## 🔗 API Endpoints

Your app now has these OAuth endpoints:

- `GET /auth/login` - Initiate Google OAuth login
- `GET /auth/callback` - Handle OAuth callback (don't call directly)
- `GET /auth/logout` - Logout and clear session
- `GET /api/auth/user` - Get current user info (JSON)
- `GET /api/auth/status` - Get authentication status (JSON)

## 📚 Additional Resources

- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [FastAPI OAuth Documentation](https://fastapi.tiangolo.com/advanced/security/)
- [Google Cloud Console](https://console.cloud.google.com/)

## 💡 Next Steps

1. **Test thoroughly** with different Google accounts
2. **Configure production environment** when ready to deploy
3. **Consider adding role-based permissions** using the crew integration
4. **Monitor authentication logs** for any issues
5. **Set up proper backup** for your session secret key

---

🎉 **Congratulations!** Your climbing webapp now has Google OAuth authentication!

For support or questions, check the troubleshooting section above or review the implementation in the source files. 