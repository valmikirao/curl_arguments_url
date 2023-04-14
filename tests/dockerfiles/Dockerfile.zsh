# NOTE, this is meant to be built with the source-root as the context
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

RUN apt-get update && apt-get install -y zsh curl jq git && \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

COPY setup.py version.txt ./
RUN pip --no-cache install -e .

COPY . /app

RUN echo 'eval "$(carl utils zsh-print-script)"' >> "$HOME/.zshrc" && \
    echo "export PS1='%% '" >> "$HOME/.zshrc" && \
    mkdir -p "$HOME/.carl/open_api"

CMD ["zsh"]
