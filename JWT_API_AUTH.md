# JWT API Authentication

This document describes how to use JWT-based authentication with the Climbing App API.

## Overview

The Climbing App now supports **hybrid authentication** that works with both:
- **Session cookies** (for web browsers)
- **JWT Bearer tokens** (for API clients, mobile apps, scripts)

This gives you the flexibility to:
- Use the web interface with automatic session management
- Build API clients that authenticate with JWT tokens
- Create mobile apps with stateless authentication
- Write scripts that interact with the API

## Authentication Methods

### 1. Session-Based Authentication (Web)
- Uses Google OAuth 2.0 flow
- Managed automatically by the web interface
- Session data stored in secure HTTP-only cookies
- Ideal for web browsers

### 2. JWT Bearer Token Authentication (API)
- Stateless JWT tokens
- Include `Authorization: Bearer <token>` header
- Perfect for API clients, mobile apps, scripts
- Tokens are self-contained with user permissions

## Getting JWT Tokens

### Step 1: Login via Web Interface
First, authenticate using the web interface at `/auth/login`. This creates a session.

### Step 2: Generate API Tokens
Once logged in, make a POST request to generate JWT tokens:

```bash
curl -X POST "http://localhost:8001/api/auth/token" \
  -H "Cookie: session=your_session_cookie" \
  -H "Content-Type: application/json"
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

## Using JWT Tokens

### Making API Requests
Include the JWT token in the `Authorization` header:

```bash
curl -X GET "http://localhost:8001/api/crew" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### Creating Resources
```bash
# Submit a new crew member
curl -X POST "http://localhost:8001/api/crew/submit" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "name=John Doe" \
  -F "skills=[\"bouldering\", \"lead climbing\"]" \
  -F "location=[\"gym\", \"outdoor\"]"

# Submit an album
curl -X POST "http://localhost:8001/api/albums/submit" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://photos.google.com/share/...",
    "crew": ["John Doe", "Jane Smith"]
  }'
```

## Token Management

### Access Tokens
- **Lifetime:** 24 hours
- **Contains:** User ID, email, name, role, permissions
- **Use:** For making API requests

### Refresh Tokens
- **Lifetime:** 30 days
- **Use:** Generate new access tokens without re-authentication

### Refreshing Tokens
When your access token expires, use the refresh token:

```bash
curl -X POST "http://localhost:8001/api/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "YOUR_REFRESH_TOKEN"}'
```

**Response:**
```json
{
  "access_token": "new_access_token...",
  "refresh_token": "new_refresh_token...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

## JWT Token Structure

### Access Token Claims
```json
{
  "sub": "user_google_id",           // Subject (user ID)
  "email": "user@example.com",
  "name": "User Name",
  "role": "user",                    // user, admin, pending
  "permissions": {
    "can_create_albums": true,
    "can_create_crew": true,
    "can_create_memes": true,
    "can_edit_own_resources": true,
    "can_delete_own_resources": true,
    "can_edit_all_resources": false,
    "can_delete_all_resources": false,
    "can_manage_users": false
  },
  "iat": 1703980800,                 // Issued at
  "exp": 1704067200,                 // Expires at
  "type": "access"
}
```

### Refresh Token Claims
```json
{
  "sub": "user_google_id",
  "iat": 1703980800,
  "exp": 1706572800,
  "type": "refresh"
}
```

## Hybrid Endpoints

Many API endpoints now support **both** authentication methods:

| Endpoint | Session Cookie | JWT Token | Notes |
|----------|---------------|-----------|-------|
| `POST /api/crew/submit` | ✅ | ✅ | Create crew members |
| `POST /api/albums/submit` | ✅ | ✅ | Submit albums |
| `POST /api/albums/edit-crew` | ✅ | ✅ | Edit album crew |
| `GET /api/auth/user` | ✅ | ✅ | Get user info |
| `POST /api/auth/token` | ✅ | ❌ | Generate JWT (requires session) |
| `POST /api/auth/refresh` | ❌ | ✅ | Refresh JWT |

## Permission System

JWT tokens include embedded permissions based on user roles:

### User Roles
- **pending**: New users awaiting approval (very limited access)
- **user**: Regular users (can create limited resources)
- **admin**: Full access to all resources and user management

### Permission Examples
```bash
# Check your permissions
curl -X GET "http://localhost:8001/api/auth/user" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

The response includes your current permissions in the `user.permissions` object.

## Error Handling

### Authentication Errors
```json
{
  "detail": "Authentication required. Provide a valid JWT Bearer token or login session.",
  "status_code": 401
}
```

### Token Expired
```json
{
  "detail": "JWT token has expired",
  "status_code": 401
}
```

### Invalid Token
```json
{
  "detail": "Invalid JWT token",
  "status_code": 401
}
```

### Permission Denied
```json
{
  "detail": "You don't have permission to create albums. Please contact an administrator.",
  "status_code": 403
}
```

## Best Practices

### Security
1. **Store tokens securely** - Never expose tokens in URLs or logs
2. **Use HTTPS** - Always use encrypted connections in production
3. **Implement token rotation** - Refresh tokens before they expire
4. **Handle errors gracefully** - Implement proper error handling for auth failures

### Token Management
1. **Cache tokens** - Store access tokens until they expire
2. **Automatic refresh** - Implement automatic token refresh
3. **Logout handling** - Discard tokens when users log out
4. **Concurrent requests** - Use the same token for multiple requests

### Example Client Implementation (JavaScript)
```javascript
class ClimbingAPIClient {
  constructor() {
    this.accessToken = localStorage.getItem('access_token');
    this.refreshToken = localStorage.getItem('refresh_token');
  }

  async makeRequest(url, options = {}) {
    // Add auth header
    options.headers = {
      ...options.headers,
      'Authorization': `Bearer ${this.accessToken}`
    };

    let response = await fetch(url, options);

    // Handle token expiration
    if (response.status === 401) {
      await this.refreshAccessToken();
      options.headers['Authorization'] = `Bearer ${this.accessToken}`;
      response = await fetch(url, options);
    }

    return response;
  }

  async refreshAccessToken() {
    const response = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: this.refreshToken })
    });

    if (response.ok) {
      const data = await response.json();
      this.accessToken = data.access_token;
      this.refreshToken = data.refresh_token;
      localStorage.setItem('access_token', this.accessToken);
      localStorage.setItem('refresh_token', this.refreshToken);
    } else {
      // Refresh failed, redirect to login
      window.location.href = '/auth/login';
    }
  }
}
```

## Migrating Existing Code

### Before (Session Only)
```python
from auth import get_current_user, require_auth

@router.post("/submit")
async def submit_resource(data: MyData, user: dict = Depends(get_current_user)):
    # Your code here
```

### After (Hybrid Authentication)
```python
from auth import get_current_user_hybrid, require_auth_hybrid

@router.post("/submit")
async def submit_resource(data: MyData, user: dict = Depends(get_current_user_hybrid)):
    """Now supports both session cookies and JWT Bearer tokens"""
    # Your code here - no other changes needed!
```

## Testing

### Test JWT Generation
```bash
# 1. Login via web interface
open http://localhost:8001/auth/login

# 2. Generate tokens (replace session cookie)
curl -X POST "http://localhost:8001/api/auth/token" \
  -H "Cookie: session=YOUR_SESSION_COOKIE"

# 3. Test API access
curl -X GET "http://localhost:8001/api/crew" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Test Token Refresh
```bash
curl -X POST "http://localhost:8001/api/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "YOUR_REFRESH_TOKEN"}'
```

## Troubleshooting

### Common Issues

1. **"Invalid JWT token" error**
   - Check token format and ensure it's properly encoded
   - Verify the token hasn't expired
   - Ensure you're using the access token, not refresh token

2. **"Authentication required" error**
   - Verify the `Authorization` header is properly formatted
   - Check that the token is included in the request
   - Ensure the endpoint supports JWT authentication

3. **Permission denied errors**
   - Check your user role and permissions via `/api/auth/user`
   - Ensure your account has been approved by an admin
   - Verify you have the required permissions for the action

4. **Token refresh failed**
   - Check if the refresh token has expired (30 days)
   - Verify the refresh token format
   - Re-authenticate via the web interface if refresh fails

---

🎉 **You now have a modern, stateless JWT authentication system that works alongside your existing session-based authentication!**

This hybrid approach gives you the best of both worlds:
- Seamless web interface experience
- Powerful API access for custom applications
- Modern, scalable authentication architecture 
