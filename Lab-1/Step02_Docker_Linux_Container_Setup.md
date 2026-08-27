# Docker Linux Container Setup

## Docker version output

![Docker_Version_SC](./Images/docker_version_SC.png)

## Hello World container output

![Hello_World_Container_SC](./Images/docker_hello_world_container_SC.png)

## cat /etc/os-release output inside ubuntu container
![Ubuntu_Container_OS_Release_SC](./Images/Ubuntu_Container_OS_release_SC.png)


## docker ps -a before and after removing my-ubuntu 

![Docker_ps_-a_Command_SC](./Images/docker_ps_-a_command.png)

## What's the difference between a Docker image and a Docker container?

The difference between a docker image and a docker container is that the docker image is like a blueprint, a static file with all the requiments listed in order to build a docker container, so you can use this docker image (file) to create a docker container or multiple docker containers from it (a running container). In the other hand a docker container is simply a lighweight running instance (bundle of an applications depedencies, its own file system, network and processes).