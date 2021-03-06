import numpy as np
import tensorflow as tf
import os
from six.moves import cPickle as pickle
from six.moves import range
from tensorflow.contrib.tensorboard.plugins import projector
#from tensorflow.contrib.session_bundle import exporter

# tf.app.flags.DEFINE_integer('training_iteration', 1000,
#                             'number of training iterations.')
# tf.app.flags.DEFINE_integer('export_version', 1, 'version number of the model.')
# tf.app.flags.DEFINE_string('work_dir', './', 'Working directory.')
# FLAGS = tf.app.flags.FLAGS

logs_path = 'logs/'
pickle_file = 'avDetect.pickle'
num_steps = 1001
export_path = logs_path #"model/"

with open(pickle_file, 'rb') as f:
  save = pickle.load(f)
  org_train_dataset = save['train_dataset']
  org_train_labels = save['train_labels']
  org_test_dataset = save['test_dataset']
  org_test_labels = save['test_labels']
  del save  # hint to help gc free up memory
  print('Training set', org_train_dataset.shape, org_train_labels.shape)
  print('Test set', org_test_dataset.shape, org_test_labels.shape)

image_size = org_train_dataset.shape[1]
num_labels = 2
num_channels = 1 # grayscale

def reformat(dataset, labels):
  dataset = dataset.reshape(
    (-1, image_size, image_size, num_channels)).astype(np.float32)
  labels = (np.arange(num_labels) == labels[:,None]).astype(np.float32)
  return dataset, labels
train_dataset, train_labels = reformat(org_train_dataset, org_train_labels)
test_dataset, test_labels = reformat(org_test_dataset, org_test_labels)
print('Training set', train_dataset.shape, train_labels.shape)
print('Test set', test_dataset.shape, test_labels.shape)

def accuracy(predictions, labels):
  return (100.0 * np.sum(np.argmax(predictions, 1) == np.argmax(labels, 1))
          / predictions.shape[0])

batch_size = 16
patch_size = 5
depth = 16
num_hidden = 32

graph = tf.Graph()

with graph.as_default():
    # Input data.

    tf_class_dataset = tf.placeholder(
        tf.float32, shape=(1, image_size, image_size, num_channels))
    tf_class_labels = tf.placeholder(tf.float32, shape=(1, num_labels))
    tf_train_dataset = tf.placeholder(
        tf.float32, shape=(batch_size, image_size, image_size, num_channels))
    tf_train_labels = tf.placeholder(tf.float32, shape=(batch_size, num_labels))
    tf_test_dataset = tf.constant(test_dataset)

    # Variables.
    layer1_weights = tf.Variable(tf.truncated_normal(
        [patch_size, patch_size, num_channels, depth], stddev=0.1))
    layer1_biases = tf.Variable(tf.zeros([depth]))
    layer2_weights = tf.Variable(tf.truncated_normal(
        [patch_size, patch_size, depth, depth], stddev=0.1))
    layer2_biases = tf.Variable(tf.constant(1.0, shape=[depth]))
    layer3_weights = tf.Variable(tf.truncated_normal(
        [image_size // 4 * image_size // 4 * depth, num_hidden], stddev=0.1))
    layer3_biases = tf.Variable(tf.constant(1.0, shape=[num_hidden]))
    layer4_weights = tf.Variable(tf.truncated_normal(
        [num_hidden, num_labels], stddev=0.1))
    layer4_biases = tf.Variable(tf.constant(1.0, shape=[num_labels]))


    # Model.
    def model(data):
        conv = tf.nn.conv2d(data, layer1_weights, [1, 1, 1, 1], padding='SAME')
        hidden = tf.nn.relu(conv + layer1_biases)
        pool = tf.nn.max_pool(hidden, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')
        conv = tf.nn.conv2d(pool, layer2_weights, [1, 1, 1, 1], padding='SAME')
        hidden = tf.nn.relu(conv + layer2_biases)
        pool = tf.nn.max_pool(hidden, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')
        shape = pool.get_shape().as_list()
        reshape = tf.reshape(pool, [shape[0], shape[1] * shape[2] * shape[3]])
        pool = tf.nn.relu(tf.matmul(reshape, layer3_weights) + layer3_biases)
        return tf.matmul(pool, layer4_weights) + layer4_biases


    # Training computation.
    logits = model(tf_train_dataset)
    loss = tf.reduce_mean(
        tf.nn.softmax_cross_entropy_with_logits(logits=logits, labels=tf_train_labels))
    tf.summary.scalar('loss', loss)

    # Optimizer.
    optimizer = tf.train.GradientDescentOptimizer(0.05).minimize(loss)

    # Predictions for the training, validation, and test data.
    train_prediction = tf.nn.softmax(logits)
    test_prediction = tf.nn.softmax(model(tf_test_dataset))
    class_prediction = tf.nn.softmax(model(tf_class_dataset))

    summary = tf.summary.merge_all()

    # Initialize a saver
    saver = tf.train.Saver(sharded=False, write_version=1)
    tf.add_to_collection('train_prediction', train_prediction)
    tf.add_to_collection('test_prediction', test_prediction)
    tf.add_to_collection('class_prediction', class_prediction)
    #tf.add_to_collection('loss', loss)
    #tf.add_to_collection('optimizer', optimizer)
    tf.add_to_collection('tf_train_dataset', tf_train_dataset)
    tf.add_to_collection('tf_train_labels', tf_train_labels)
    tf.add_to_collection('tf_class_dataset', tf_class_dataset)
    tf.add_to_collection('tf_class_labels', tf_class_labels)

with tf.Session(graph=graph) as session:
  summary_writer = tf.summary.FileWriter(logs_path, session.graph)
  tf.initialize_all_variables().run()

  print('Initialized')
  for step in range(num_steps):
    offset = (step * batch_size) % (train_labels.shape[0] - batch_size)
    batch_data = train_dataset[offset:(offset + batch_size), :, :, :]
    batch_labels = train_labels[offset:(offset + batch_size), :]
    feed_dict = {tf_train_dataset : batch_data, tf_train_labels : batch_labels}
    _, l, predictions = session.run(
      [optimizer, loss, train_prediction], feed_dict=feed_dict)
    if (step % 50 == 0):
      summary_str = session.run(summary, feed_dict=feed_dict)
      summary_writer.add_summary(summary_str, step)
      summary_writer.flush()
      print('Minibatch loss at step %d: %f' % (step, l))
      print('Minibatch accuracy: %.1f%%' % accuracy(predictions, batch_labels))
  print('Test accuracy: %.1f%%' % accuracy(test_prediction.eval(), test_labels))
  save_path = saver.save(session, export_path+"my_model")
  print("Model saved in file: %s" % save_path)

  # export model
  #
  # print('Exporting trained model to %s' % export_path)
  # model_exporter = exporter.Exporter(saver)
  # model_exporter.init(
  #       session.graph.as_graph_def(),
  #       named_graph_signatures={
  #           'inputs': exporter.generic_signature({'images': tf_train_dataset}),
  #           'outputs': exporter.generic_signature({'scores': logits})})
  # model_exporter.export(export_path, tf.constant(FLAGS.export_version), session)
  # print('Done exporting!')




