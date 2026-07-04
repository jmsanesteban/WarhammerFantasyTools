# Copy this file to config.ps1 (gitignored) and fill in your real lab values.
# config.ps1 is never committed - it's where host IPs, users and key paths live.

$SshKey = "$HOME\.ssh\wft_guest_ed25519"
$StagingHost = "deploy@STAGING_IP_HERE"
$ProdHost = "deploy@PROD_IP_HERE"
$StagingUrl = "http://STAGING_IP_HERE:5000"
$ProdUrl = "http://PROD_IP_HERE:5000"
