# Contributing to SISTER

Thank you for your interest in contributing to SISTER (Star Interrogation System for Traits and Equipment Recognition)! This document provides guidelines and information for contributors.

## Ways to Contribute

### 1. Submit Training Data

The most valuable way to contribute is by submitting build screenshots:
- Visit our [training data submission page](https://sister.example.com/training/submit)
- Follow the screenshot guidelines carefully
- Provide clear, high-quality screenshots
- Include proper consent for data usage

### 2. Code Contributions

#### Setting Up Development Environment

1. Fork the repository
2. Clone your fork:
```bash
git clone https://github.com/phillipod/SISTER.git
cd SISTER
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```

#### System Requirements

- Python 3.11 or higher
- 8GB RAM minimum
- Storage:
  - Source install: 500MB
  - MSI installer: 1.5GB

Note: Icon assets are downloaded on-demand. The `--download` command is only needed if you want to pre-download all icons, and is required before using `--build-hash-cache`.

#### Pull Request Process

1. Create a new branch for your feature:
```bash
git checkout -b feature/your-feature-name
```
2. Make your changes
3. Test your changes thoroughly
4. Update documentation if needed
5. Submit a pull request

#### Code Style

- Follow PEP 8 guidelines
- Use meaningful variable and function names
- Add comments for complex logic
- Include docstrings for functions and classes

### 3. Documentation

Help improve our documentation by:
- Fixing typos or unclear instructions
- Adding examples and use cases
- Improving installation guides
- Creating tutorials

### 4. Testing

- Help expand our test suite
- Report bugs with detailed reproduction steps
- Verify fixes and improvements

## Development Setup

### Running Tests

```bash
python -m pytest test_suite/
```

## Communication

- Use GitHub Issues for bug reports and feature requests
- Join our community discussions on GitHub
- Follow our code of conduct

## Questions?

If you have questions about contributing, please:
1. Check existing documentation
2. Search through issues
3. Create a new issue with the question label

Thank you for contributing to SISTER! 