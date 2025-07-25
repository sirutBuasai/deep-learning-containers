FROM docker.io/vllm/vllm-openai:v0.9.2 as final
ARG PYTHON="python3"
ARG EFA_VERSION="1.42.0"
LABEL maintainer="Amazon AI"
LABEL dlc_major_version="1"
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DLC_CONTAINER_TYPE=base \
    # Python won’t try to write .pyc or .pyo files on the import of source modules
    # Force stdin, stdout and stderr to be totally unbuffered. Good for logging
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    LD_LIBRARY_PATH="/usr/local/lib:/opt/amazon/ofi-nccl/lib/x86_64-linux-gnu:/opt/amazon/openmpi/lib:/opt/amazon/efa/lib:/usr/local/cuda/lib64:${LD_LIBRARY_PATH}" \
    PATH="/opt/amazon/openmpi/bin:/opt/amazon/efa/bin:/usr/local/cuda/bin:${PATH}"

WORKDIR /

COPY install_efa.sh install_efa.sh
COPY deep_learning_container.py /usr/local/bin/deep_learning_container.py
COPY bash_telemetry.sh /usr/local/bin/bash_telemetry.sh
COPY dockerd_entrypoint.sh /usr/local/bin/dockerd_entrypoint.sh
RUN chmod +x /usr/local/bin/deep_learning_container.py && \
    chmod +x /usr/local/bin/bash_telemetry.sh && \
    chmod +x /usr/local/bin/dockerd_entrypoint.sh && \
    echo 'source /usr/local/bin/bash_telemetry.sh' >> /etc/bash.bashrc && \
    # Install EFA
    bash install_efa.sh ${EFA_VERSION} && \
    rm install_efa.sh && \
    # OSS compliance and software update
    apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --allow-change-held-packages --no-install-recommends unzip && \
    apt-get clean && \
    HOME_DIR=/root && \
    curl -o ${HOME_DIR}/oss_compliance.zip https://aws-dlinfra-utilities.s3.amazonaws.com/oss_compliance.zip && \
    unzip ${HOME_DIR}/oss_compliance.zip -d ${HOME_DIR}/ && \
    cp ${HOME_DIR}/oss_compliance/test/testOSSCompliance /usr/local/bin/testOSSCompliance && \
    chmod +x /usr/local/bin/testOSSCompliance && \
    chmod +x ${HOME_DIR}/oss_compliance/generate_oss_compliance.sh && \
    ${HOME_DIR}/oss_compliance/generate_oss_compliance.sh ${HOME_DIR} ${PYTHON} && \
    # create symlink for python
    ln -s /usr/bin/python3 /usr/bin/python && \
    # clean up
    rm -rf ${HOME_DIR}/oss_compliance* && \
    rm -rf /tmp/tmp* && \
    rm -rf /tmp/uv* && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /root/.cache | true

RUN mkdir -p /tmp/nvjpeg \
    && cd /tmp/nvjpeg \
    && wget https://developer.download.nvidia.com/compute/cuda/redist/libnvjpeg/linux-x86_64/libnvjpeg-linux-x86_64-12.4.0.76-archive.tar.xz \
    && tar -xvf libnvjpeg-linux-x86_64-12.4.0.76-archive.tar.xz \
    && rm -rf /usr/local/cuda/targets/x86_64-linux/lib/libnvjpeg* \
    && rm -rf /usr/local/cuda/targets/x86_64-linux/include/nvjpeg.h \
    && cp libnvjpeg-linux-x86_64-12.4.0.76-archive/lib/libnvjpeg* /usr/local/cuda/targets/x86_64-linux/lib/ \
    && cp libnvjpeg-linux-x86_64-12.4.0.76-archive/include/* /usr/local/cuda/targets/x86_64-linux/include/ \
    && rm -rf /tmp/nvjpeg \ 
      # remove cuobjdump and nvdisasm
    && rm -rf /usr/local/cuda/bin/cuobjdump* \ 
    && rm -rf /usr/local/cuda/bin/nvdisasm*  

ENTRYPOINT ["/usr/local/bin/dockerd_entrypoint.sh"]