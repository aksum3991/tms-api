pipeline {
    agent any

    environment {
        REGISTRY = '199900000'  // Docker Hub username
        IMAGE_NAME = 'tms'     // Docker image name
        IMAGE_TAG = 'lat'       // Version tag
        DOCKER_CREDENTIALS = 'gatepass_dockerhub'  // Jenkins credential ID for Docker login
        SONARQUBE_CREDENTIALS = 'gatepass_sonarqube'  // Jenkins credential ID for SonarQube
        SONARQUBE_URL = "http://sonar:9000"  // SonarQube server URL
        //PROJECT_KEY = "gatepassvms"  // Unique key for your SonarQube project
        EMAIL_RECIPIENTS = ''
        DOTNET_TOOLS_PATH = "$HOME/.dotnet/tools" // Path for .NET global tools
       
    }

    stages {

        stage('Checkout Code') {
            steps {
                git branch: 'main', url: 'git@github.com:aksum3991/tms-api.git'
            }
        }

        stage('build') {
              steps{
                  script {
                      sh ''' #!/bin/bash
                        echo "Building Docker image..."
                        export COMPOSE_BAKE=true
                        docker compose up -d

                      '''
                  }
              }
        }

    
    }

    post {
        success {
            echo 'Deployment Successful!'
            emailext(
                subject: "Deployment Successful - TMS API",
                body: "The TMS application has been successfully deployed.",
                to: "$EMAIL_RECIPIENTS",
                 attachLog: true
            )
        }
        failure {
            echo 'Deployment Failed. Check logs.'
            emailext(
                subject: "Deployment Failed - TMS API,
                body: "The deployment has failed. Please check the Jenkins logs for details.",
                to: "$EMAIL_RECIPIENTS",
                attachLog: true
            )
        }
    }
}
