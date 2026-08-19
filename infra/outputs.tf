output "app_url" {
  description = "Public application URL"
  value       = "https://${aws_cloudfront_distribution.app.domain_name}"
}

output "api_url" {
  description = "Direct API Gateway URL (CloudFront is the normal public entry point)"
  value       = aws_apigatewayv2_api.backend.api_endpoint
}

output "ecr_repository_url" {
  description = "Backend container repository"
  value       = aws_ecr_repository.backend.repository_url
}

output "frontend_bucket_name" {
  description = "Private S3 bucket containing the Vite build"
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution used for cache invalidations"
  value       = aws_cloudfront_distribution.app.id
}

output "gemini_parameter_name" {
  description = "Secure SSM parameter read by the Lambda function"
  value       = local.gemini_parameter_name
}
