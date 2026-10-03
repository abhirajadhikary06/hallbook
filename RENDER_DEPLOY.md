# Deploy to Render.com

This guide shows how to deploy the Hall Booking Platform to Render.com using Docker.

## 📋 Prerequisites

1. A [Render.com](https://render.com) account (free tier available)
2. Your code pushed to GitHub/GitLab/Bitbucket
3. A PostgreSQL database (Render provides free PostgreSQL)

## 🚀 Quick Deploy

### Step 1: Create PostgreSQL Database

1. Go to [Render Dashboard](https://dashboard.render.com/)
2. Click **New +** → **PostgreSQL**
3. Configure:
   - **Name**: `hall-booking-db`
   - **Database**: `hallbook`
   - **User**: `hallbook`
   - **Region**: Choose closest to your users
   - **Plan**: Free (or paid for production)
4. Click **Create Database**
5. **Save the "Internal Database URL"** - you'll need this!

### Step 2: Create Web Service

1. Click **New +** → **Web Service**
2. Connect your Git repository
3. Configure:
   - **Name**: `hall-booking-platform`
   - **Region**: Same as your database
   - **Branch**: `main` (or your default branch)
   - **Root Directory**: `hall_booking` (if repo root) or leave empty
   - **Environment**: `Docker`
   - **Plan**: Free (or paid for production)

### Step 3: Set Environment Variables

Click **Advanced** and add these environment variables:

| Key | Value | Notes |
|-----|-------|-------|
| `DATABASE_URL` | (Your Internal Database URL from Step 1) | Required - PostgreSQL connection |
| `COOKIE_SECRET` | (Generate random 32+ char string) | Required - Session security |
| `PORT` | `8888` | Optional - Render sets this automatically |
| `DEBUG` | `0` | Optional - Production mode |

**Example DATABASE_URL:**
```
postgresql://hallbook:password@dpg-xxxxx.oregon-postgres.render.com/hallbook
```

**Generate COOKIE_SECRET:**
```python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 4: Deploy

1. Click **Create Web Service**
2. Wait for deployment (5-10 minutes)
3. Access your app at: `https://your-service-name.onrender.com`

## 🔐 Default Credentials

After first deployment, log in with:

- **Admin**: `admin` / `admin123`
- **Demo User**: `demo_user` / `user123`

⚠️ **IMPORTANT**: Change these passwords immediately in production!

## 📝 Environment Variables Explained

### Required Variables

**DATABASE_URL**
- Format: `postgresql://username:password@host:port/database`
- Get from Render PostgreSQL internal URL
- Example: `postgresql://hallbook:pass@dpg-xxx.oregon-postgres.render.com/hallbook`

**COOKIE_SECRET**
- Random secret key for session cookies
- Must be 32+ characters
- Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- Keep this secret and never commit to Git!

### Optional Variables

**PORT**
- Default: `8888`
- Render automatically sets this, usually not needed

**DEBUG**
- Set to `0` for production
- Set to `1` only for debugging (not recommended in production)

## 🔄 Updates

Render automatically redeploys when you push to your connected branch:

```bash
git add .
git commit -m "Update application"
git push origin main
```

Or manually redeploy from Render Dashboard:
1. Go to your web service
2. Click **Manual Deploy** → **Deploy latest commit**

## 📊 Monitoring

### View Logs
1. Go to your web service in Render Dashboard
2. Click **Logs** tab
3. See real-time application logs

### Metrics
1. Click **Metrics** tab
2. View CPU, Memory, Response times

## 💾 Database Management

### Access Database
1. Go to your PostgreSQL database in Render
2. Click **Connect** → **External Connection**
3. Use provided connection string with your database tool (pgAdmin, DBeaver, etc.)

### Backup Database
Render automatically backs up paid PostgreSQL instances. For free tier:

```bash
# From your local machine
pg_dump -h dpg-xxx.oregon-postgres.render.com -U hallbook -d hallbook > backup.sql

# Restore
psql -h dpg-xxx.oregon-postgres.render.com -U hallbook -d hallbook < backup.sql
```

## 🔒 Security Best Practices

✅ Use strong COOKIE_SECRET (32+ characters)  
✅ Change default admin password immediately  
✅ Use environment variables (never hardcode secrets)  
✅ Keep DEBUG=0 in production  
✅ Use HTTPS (Render provides automatically)  
✅ Regular database backups  
✅ Monitor logs for suspicious activity  

## 🐛 Troubleshooting

### Build Fails

**Check Dockerfile:**
- Ensure `Dockerfile` is in the correct directory
- Verify `requirements.txt` includes all dependencies

**View Build Logs:**
- Render Dashboard → Your Service → Logs
- Look for error messages during build

### Application Won't Start

**Check Environment Variables:**
- Verify `DATABASE_URL` is correct
- Ensure `COOKIE_SECRET` is set
- Check logs for specific errors

**Common Issues:**
- Database not accessible: Check if database is in same region
- Port conflicts: Render handles PORT automatically
- Missing dependencies: Check requirements.txt

### Database Connection Errors

**Verify DATABASE_URL:**
```python
# Check in Render Shell
echo $DATABASE_URL
```

**Test Connection:**
- Use External Connection string to test with database client
- Ensure database is running (green status in Render)

### Application Slow / Crashing

**Free Tier Limitations:**
- Services spin down after 15 minutes of inactivity
- First request after spindown takes ~30 seconds
- 750 hours/month free compute time
- Consider upgrading to paid plan for production

**Check Resource Usage:**
- Render Dashboard → Your Service → Metrics
- Look for memory/CPU spikes

## 📈 Scaling

### Upgrade Plan
For production use, consider:
- **Starter Plan** ($7/month): Always on, no spin down
- **Standard Plan** ($25/month): More resources, faster
- **Pro Plan** ($85/month): High performance

### Horizontal Scaling
Render supports multiple instances:
1. Go to your service settings
2. Set **Instance Count** > 1
3. Traffic automatically load balanced

## 💰 Cost Estimate

**Free Tier (Development/Testing):**
- Web Service: Free (750 hours/month)
- PostgreSQL: Free (90 day expiration, 1GB)
- Total: $0/month

**Basic Production:**
- Web Service (Starter): $7/month
- PostgreSQL (Starter): $7/month
- Total: $14/month

**Production:**
- Web Service (Standard): $25/month
- PostgreSQL (Standard): $20/month
- Total: $45/month

## 🌐 Custom Domain

1. Go to your web service
2. Click **Settings** → **Custom Domain**
3. Add your domain
4. Update DNS records as instructed
5. Render provides free SSL certificate

## 📚 Additional Resources

- [Render Documentation](https://render.com/docs)
- [Render Deploy from Docker](https://render.com/docs/deploy-docker)
- [Environment Variables](https://render.com/docs/environment-variables)
- [PostgreSQL on Render](https://render.com/docs/databases)

## 🎉 Success!

Your Hall Booking Platform is now deployed on Render! 

Access at: `https://your-service-name.onrender.com`

Need help? Check [Render Community](https://community.render.com/) or [Support](https://render.com/support)
