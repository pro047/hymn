# Hymn Terraform Stack (A안)

Preset for a Seoul 2AZ VPC and minimal app stack (EC2 + RDS + S3 + ECR + state backend).

## Layout
- `state-bootstrap/` – creates the S3 state bucket and DynamoDB lock table (no backend).
- `backend.tf` – points Terraform backend at the state bucket/table (update names if you change them).
- `main.tf` – wires modules for network, IAM/EC2, RDS, S3 (images), ECR.
- `modules/*` – reusable building blocks.

## Defaults (per request)
- VPC 10.0.0.0/16, public 10.0.1.0/24 & 10.0.2.0/24, private 10.0.11.0/24 & 10.0.12.0/24, 1× NAT.
- RDS Postgres 16, db.t4g.micro, gp3 20GB, backup 7d, public=false, multi-AZ=false, maintenance `sun:04:00-05:00`, backup window `03:00-04:00`, deletion protection prod only.
- S3 images bucket: public access block on, SSE-S3 on, CORS GET/PUT/HEAD, Expose ETag, MaxAge 3000. Add `allowed_origins` later (kept empty by default).
- ECR: scan_on_push true, lifecycle keep latest 20 images.
- EC2: t4g.micro, Ubuntu 22.04 ARM, EBS 30GB gp3, SG: 22 from `allowed_ssh_cidr`, 80/443 from `allowed_http_cidr`, EIP attach by default, IAM role with ECR pull + S3 access (+ optional SSM).

## Quickstart
### 1) Bootstrap state (once)
```sh
cd infra/state-bootstrap
terraform init
terraform apply -auto-approve
```
Names default to `hymn-tfstate` and `hymn-terraform-lock`. Change in `variables.tf` if desired.

### 2) Main stack
Edit `infra/backend.tf` if you changed bucket/table names. Then:
```sh
cd infra
terraform init
terraform plan \
  -var 'ssh_key_name=your-keypair' \
  -var 'rds_password=change-me' \
  -var 'image_bucket_allowed_origins=["https://api.your-domain.com"]'
terraform apply
```

## Variables to set
- `ssh_key_name` (required) – existing EC2 key pair.
- `rds_password` (required, sensitive).
- `image_bucket_allowed_origins` – keep empty until you know the web origins; add domains for CORS.
- `project`/`environment` – default `hymn`/`dev`; update if you want different names.
- `allowed_ssh_cidr` – lock down SSH (default is 0.0.0.0/0; replace with your IP/32).
- `allowed_http_cidr` – HTTP/HTTPS exposure (default 0.0.0.0/0).
- `rds_backup_retention`, `rds_allocated_storage` if you need overrides.

## Notes
- Backend S3 and DDB are protected from destroy; RDS final snapshot is kept (`final_snapshot_identifier` set).
- Parameter group sets `TimeZone=Asia/Seoul` for Postgres 16.
- EC2 user_data is empty; add bootstrap as needed.
