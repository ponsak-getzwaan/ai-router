variable "aws_region" {
  type        = string
  default     = "ap-southeast-1"
  description = "AWS region. Locked to ap-southeast-1 for SG data residency."
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Deployment environment (prod / staging)."
}

variable "project" {
  type        = string
  default     = "ai-router"
  description = "Project slug — used as prefix on all resource names."
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "orchestrator_cpu" {
  type    = number
  default = 512
}

variable "orchestrator_memory" {
  type    = number
  default = 1024
}

variable "presidio_cpu" {
  type    = number
  default = 1024
  description = "Presidio needs more CPU for the spaCy NLP model."
}

variable "presidio_memory" {
  type    = number
  default = 2048
  description = "spaCy model requires ~200MB; 2GB gives headroom."
}

variable "service_cpu" {
  type    = number
  default = 256
  description = "CPU units for Bouncer, Classifier, Strategist, Adapters."
}

variable "service_memory" {
  type    = number
  default = 512
  description = "Memory MB for Bouncer, Classifier, Strategist, Adapters."
}
