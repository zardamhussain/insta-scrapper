help:
	@echo "Available targets:"
	@echo "  build    - Build the Docker images"
	@echo "  up       - Start the services with 5 app replicas"
	@echo "  down     - Stop and remove the services"
	@echo "  restart  - Restart the services (down then up)"
	@echo "  logs     - View logs from all services"
	@echo "  clean    - Remove all Docker containers, images, and volumes (use with caution)"
	@echo "  status   - Show the status of the containers"

build:
	docker-compose build

up:
	docker-compose up -d --scale app=5
	@echo "Setup is running. Access the API at http://localhost/api/reel"

down:
	docker-compose down

restart: down up

logs:
	docker-compose logs -f

clean:
	docker-compose down --rmi all --volumes --remove-orphans

status:
	docker-compose ps