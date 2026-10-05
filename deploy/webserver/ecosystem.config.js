// pm2 ecosystem file fuer das Backend auf dem Webserver.
// Start (von beliebigem Verzeichnis aus):  pm2 start deploy/webserver/ecosystem.config.js
// Am einfachsten richtet deploy/webserver/install.sh alles ein (venv, Build, pm2, nginx).
// Das Frontend liefert nginx als statischen Build aus (nginx-monitoring.conf.template),
// daher laeuft hier nur noch das Backend.
module.exports = {
  apps: [
    {
      name: "monitoring-backend",
      cwd: __dirname,
      script: "./run-backend.sh",
      interpreter: "bash",
      autorestart: true,
    },
  ],
};
