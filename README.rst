Real-Time Topic Discovery Tools (TOM + Google Custom Search Engine API)
=======================================================================
Flask's based webapp for targeted topic discovery. Performs custom searches with Google's CSE API
looking for latest articles on a subject. With the resulting URLs, it scrapes all of the textual
content and runs a topic discovery algorithm. Results are segregated by subject, timeframe and
discovered topics. This results can be consumed navigating through the app.

Github's AdrienGuille/TOM project to be credited for the analytical approach and most of the webapp
UI and UX design.

**SCOPE:  [New Product Development]**

**TARGET: [Final Product Development]**

**STATUS: [Production Ready]**

Potential Improvements:
-----------------------
Although current status for the project is "Production Ready" in terms of stability, we've identified
some improvements that could suppose a substantial improvement:

- Machine Learning/Deep Learning Clustering Algorithm for Topic Discovery, that accounts for trends and
  not so simple topic-word relationships.
- Partial Rework of UI, to put some more emphasis on Topic Discovery

Notes:
------
In case you want to deploy it with Docker, you should take into account that this project Dockerfile
includes commands for nltk dependency downloading, so depending on the available bandwidth build phase
will take some time. In case you wanted to modify anything regarding the deployment phase, maybe you
should consider splitting the Dockerfile, in order to avoid repeating compilation multiple times.
