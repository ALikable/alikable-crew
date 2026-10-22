# Deploying Alikable on AWS EC2

> **Status: torn down on 2026-10-22.** The instance, its disk, the Elastic IP, the security
> group and the key pair below were all deleted, so the IDs and the IP no longer exist. To
> deploy again, follow [Redeploying](#redeploying); the app changes and `deploy/` files remain.

Alikable ran on a single EC2 instance, served over plain HTTP behind a login. This file
describes what changed in the app to make that work, which AWS services it used, what ran
on the server, and how to operate it.

The login password and the SSH key were kept on the deploying laptop
(`~/.ssh/alikable-login.txt` and `~/.ssh/alikable-key.pem`), never in this repo.

## Changes to the app

Only three files in `src/alikable/` changed. The crew, agents, tasks and flows are untouched.

### `ui/preview.py`: the site preview works on a server

- **Before:** "Open in browser" called `webbrowser.open(...)` with a `file://` path. That opens
  a browser on whichever computer runs the app: fine on a laptop, but on EC2 it tried to open
  a browser on the server and the user saw nothing.
- **Now:** the button is a link. Gradio serves the page itself, at a URL like
  `/gradio_api/file=/opt/.../site/index.html` (allowed by `allowed_paths=[PROJECTS]` in
  `launch()`), and the link opens it in a new tab. Relative links such as `styles.css` and
  `js/app.js` still load, because they resolve against the page's URL.

### `app.py`: `launch()` reads its settings from `.env`

| Variable | Default | What it does |
|---|---|---|
| `ALIKABLE_HOST` | `127.0.0.1` | Address the app listens on |
| `ALIKABLE_PORT` | `7860` | Port it listens on |
| `ALIKABLE_USER` / `ALIKABLE_PASSWORD` | not set | When both are set, Gradio shows a login page before anything else |

The login also covers the preview pages, because Gradio checks it on the file route. With
none of these set, the app runs locally exactly as before: same address and port, no login.

### `ui/__init__.py`

A one-line docstring update describing `preview.py`.

## AWS services

Only **EC2** and the pieces that come with it, in `us-east-1`:

| Piece | ID / value | What it is | Why |
|---|---|---|---|
| EC2 instance (`t3.medium`, Ubuntu 24.04) | `i-00167e40f36dc9dbd` | A virtual server with 2 vCPUs and 4 GB of RAM | Runs the Gradio app, Caddy and Node. The AI work happens at OpenAI, so no GPU is needed. |
| EBS volume (30 GB gp3) | tagged `alikable` | The instance's disk | Holds the code, the Python environment and `output/` (projects and memory). It survives reboots, not termination. |
| Elastic IP | `184.197.213.167` | A fixed public IP | Without it, the address changes whenever the instance stops and starts. |
| Security group | `alikable-sg` (`sg-037fe08f7b45e10b8`) | The instance's firewall | Allows SSH (22) from the deployer's IP only and HTTP (80) from anywhere. Everything else, including 7860, is blocked. |
| Key pair | `alikable-key` | The SSH key | The private key is `~/.ssh/alikable-key.pem` on the deploying laptop. |
| SSM public parameter (read only) | `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id` | AWS's published ID of the latest Ubuntu image | Used to pick the image to launch. Nothing was created. |

Not used: load balancer, domain or Route 53, HTTPS certificate, S3, database, containers.

Cost: about $36/month while the instance runs (about $30 instance, $2.40 disk, $3.65 public IPv4), plus OpenAI usage. Stopped, the disk and IP still cost about $6/month.

## Software on the instance

| Software | Role |
|---|---|
| **Caddy** | Listens on port 80 and passes requests to the app on `127.0.0.1:7860`, including the WebSocket and streaming connections Gradio uses. Config: `deploy/Caddyfile`. |
| **systemd** | Runs the app as the `alikable` user from `/opt/alikable-crew/alikable`, and restarts it if it crashes or the server reboots. Unit: `deploy/alikable.service`. |
| **Node.js 22** | Needed by the Code Reviewer's filesystem MCP (`npx`) and the build checker (`node --check`). The MCP server is installed globally so the first review doesn't wait for a download. |
| **uv / Python** | The same dependencies as locally, installed from `uv.lock`. |

The server's `.env` (`chmod 600`, owned by `alikable`) holds the OpenAI key, `MODEL`, the
`ALIKABLE_*` settings and the login. `deploy/env.example` is its template.

## Files in `deploy/`

| File | Run where | What it does |
|---|---|---|
| `push.sh <ip> <key>` | Laptop | Copies the working tree to the server (never `.env`, `.venv` or `output/`). If the server is set up, reinstalls dependencies and restarts the app. |
| `setup.sh` | Server, once | Installs Node 22, Caddy and uv, creates the `alikable` user, installs dependencies, sets up `.env`, the service and Caddy. Safe to run again. |
| `alikable.service` | Server | The systemd unit. |
| `Caddyfile` | Server | Plain HTTP on port 80, proxied to the app. |
| `env.example` | Server | Template for the server's `.env`. |

## Operating it

```bash
# Ship code changes (copies uncommitted changes too; restarting stops any running build)
deploy/push.sh 184.197.213.167 ~/.ssh/alikable-key.pem

# Logs
ssh -i ~/.ssh/alikable-key.pem ubuntu@184.197.213.167 sudo journalctl -u alikable -f

# Restart, or edit the server's .env (then restart)
ssh -i ~/.ssh/alikable-key.pem ubuntu@184.197.213.167 sudo systemctl restart alikable
ssh -i ~/.ssh/alikable-key.pem ubuntu@184.197.213.167 sudo -u alikable nano /opt/alikable-crew/alikable/.env

# Stop paying for compute while keeping the disk and IP (an idle Elastic IP is still billed)
aws ec2 stop-instances --region us-east-1 --instance-ids i-00167e40f36dc9dbd
aws ec2 start-instances --region us-east-1 --instance-ids i-00167e40f36dc9dbd
```

If your IP changes, SSH stops working until the security group rule is updated:

```bash
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id sg-037fe08f7b45e10b8 \
  --protocol tcp --port 22 --cidr "$(curl -s https://checkip.amazonaws.com)/32"
```

## Redeploying

The IDs and IP below will be new. Run from the project root, in `us-east-1`:

```bash
export AWS_REGION=us-east-1
aws ec2 create-key-pair --key-name alikable-key --key-type ed25519 --query KeyMaterial --output text > ~/.ssh/alikable-key.pem
chmod 400 ~/.ssh/alikable-key.pem
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 create-security-group --group-name alikable-sg --description "Alikable" --vpc-id $VPC --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 22 --cidr "$(curl -s https://checkip.amazonaws.com)/32"
aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 80 --cidr 0.0.0.0/0
AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
IID=$(aws ec2 run-instances --image-id $AMI --instance-type t3.medium --key-name alikable-key --security-group-ids $SG \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3}' --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=alikable}]' --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --instance-ids $IID
ALLOC=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id $IID --allocation-id $ALLOC
IP=$(aws ec2 describe-addresses --allocation-ids $ALLOC --query 'Addresses[0].PublicIp' --output text)

deploy/push.sh $IP ~/.ssh/alikable-key.pem       # copies the code
# put a .env on the server (local .env + ALIKABLE_USER / ALIKABLE_PASSWORD), then:
ssh -i ~/.ssh/alikable-key.pem ubuntu@$IP sudo /opt/alikable-crew/alikable/deploy/setup.sh
```

Tearing it down again: terminate the instance (deletes its disk), release the Elastic IP,
then delete the security group and the key pair.

## Known limits

- **No HTTPS.** The login and all traffic travel in plain text. To add HTTPS, point a domain at
  the Elastic IP, replace `:80` in `deploy/Caddyfile` with the domain, open port 443, and push.
- **No backups.** `output/` lives only on the EBS volume. Set up EBS snapshots (Data Lifecycle
  Manager) before relying on it.
- **One shared workspace.** Everyone who logs in sees every project in the picker.
- **Restarts stop running jobs.** A push or restart ends any crew job in progress.
- **Not yet tested end to end on the server.** The app, login and routing are verified; a full
  build (including the Code Reviewer's `npx` MCP) has not been run there yet.
