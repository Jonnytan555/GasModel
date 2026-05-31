resource "aws_ecr_repository" "gas_model" {
  name                 = "gas-model"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "gas_scraper" {
  name                 = "gas-scraper"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }
}

# Keep only the last 5 images to control storage costs
resource "aws_ecr_lifecycle_policy" "gas_model" {
  repository = aws_ecr_repository.gas_model.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "gas_scraper" {
  repository = aws_ecr_repository.gas_scraper.name
  policy     = aws_ecr_lifecycle_policy.gas_model.policy
}
