-- ============================================================
-- pg_cron job schedules
-- Run AFTER Edge Functions are deployed
-- ============================================================

-- Publish scheduled posts every 5 minutes
SELECT cron.schedule(
    'publish-scheduled',
    '*/5 * * * *',
    $$
    SELECT net.http_post(
        url := current_setting('app.settings.supabase_url') || '/functions/v1/publish-scheduled',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || current_setting('app.settings.service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'::jsonb
    );
    $$
);

-- Fetch analytics daily at 6am UTC
SELECT cron.schedule(
    'fetch-analytics',
    '0 6 * * *',
    $$
    SELECT net.http_post(
        url := current_setting('app.settings.supabase_url') || '/functions/v1/fetch-analytics',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || current_setting('app.settings.service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'::jsonb
    );
    $$
);

-- Refresh IG token every 50 days
SELECT cron.schedule(
    'refresh-token',
    '0 0 */50 * *',
    $$
    SELECT net.http_post(
        url := current_setting('app.settings.supabase_url') || '/functions/v1/refresh-token',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || current_setting('app.settings.service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'::jsonb
    );
    $$
);
